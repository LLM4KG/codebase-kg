"""Unit tests for the per-candidate orchestration (LLM + harness + KG all mocked)."""

from __future__ import annotations

import json

import pytest

from src.generation import orchestrator as orch
from src.generation.orchestrator import Candidate, build_candidates
from src.harness.models import HarnessStage
from src.retrieval.config import ExperimentConfig, RetrievalConditionConfig, RunConfig


# --------------------------------------------------------------------------- #
# Candidate matrix                                                            #
# --------------------------------------------------------------------------- #
def test_build_candidates_primary_is_45():
    """3 tasks x 3 conditions x n=5. `whole_file` joined the default set with the
    output-format work — it is the only non-KG arm that can reach build/test."""
    cands = build_candidates("claude_primary", n=5)
    assert len(cands) == 45
    assert len({c.candidate_id for c in cands}) == 45
    assert {c.condition for c in cands} == {"floor", "whole_file", "kg_augmented"}


def test_build_candidates_open_model_leg_matches_primary_shape():
    """The open-model leg ran P1 only until 2026-07-30. P1's KG arm was
    expected-fail by construction, so that leg measured plumbing, not code
    generation. Both legs now span the same three tasks."""
    cands = build_candidates("qwen_robustness", n=5)
    assert len(cands) == 45
    assert {c.task_id for c in cands} == {"P1", "P2", "P3"}
    assert {c.condition for c in cands} == {"floor", "whole_file", "kg_augmented"}


def test_build_candidates_honours_explicit_conditions():
    """`--conditions` reproduces the original two-arm pilot shape."""
    cands = build_candidates("claude_primary", n=5, conditions=("floor", "kg_augmented"))
    assert len(cands) == 30
    assert {c.condition for c in cands} == {"floor", "kg_augmented"}


def test_candidate_id_format():
    c = Candidate(run_id="r", run_name="r", task_id="P1", project_name="p", condition="floor", index=3)
    assert c.candidate_id == "P1__floor__n3"


# --------------------------------------------------------------------------- #
# Per-candidate pipeline                                                      #
# --------------------------------------------------------------------------- #
async def test_floor_passes_empty_context_to_generator(wired):
    cand = Candidate(run_id="claude_primary", run_name="claude_primary", task_id="P1", project_name="rsc", condition="floor", index=1)
    hr = await orch.run_one_candidate(cand, timeouts={}, llm_call_factory=wired["llm_factory"])

    assert hr.stage is HarnessStage.test_pass
    gen = wired["gen"][0]
    # Floor context is empty → build_generation_prompt omits a context block.
    assert "## CONTEXT BLOCK" not in gen["prompt"]
    assert gen["call_purpose"] == "generator"
    assert gen["temperature"] == 0.0
    assert gen["model"] == "test-model"
    assert wired["kg_loaded"] == []  # floor never loads a KG


async def test_kg_augmented_uses_resolved_project_id_and_context(wired):
    cand = Candidate(run_id="claude_primary", run_name="claude_primary", task_id="P1", project_name="rsc", condition="kg_augmented", index=1)
    await orch.run_one_candidate(cand, timeouts={}, llm_call_factory=wired["llm_factory"])

    assert wired["kg_project_id"] == "HASH::rsc"          # resolved hash, not friendly name
    assert "## CONTEXT BLOCK" in wired["gen"][0]["prompt"]  # retrieved context reached the prompt


async def test_same_model_for_classifier_and_generator(wired):
    """D-LLM3: the retriever (classifier) and generator use the same run model."""
    cand = Candidate(run_id="claude_primary", run_name="claude_primary", task_id="P1", project_name="rsc", condition="kg_augmented", index=1)
    await orch.run_one_candidate(cand, timeouts={}, llm_call_factory=wired["llm_factory"])
    assert wired["retriever_model"] == ["test-model"]
    assert wired["gen"][0]["model"] == "test-model"


async def test_timeout_passed_through(wired):
    cand = Candidate(run_id="claude_primary", run_name="claude_primary", task_id="P1", project_name="rsc", condition="floor", index=1)
    await orch.run_one_candidate(cand, timeouts={"P1": 90000}, llm_call_factory=wired["llm_factory"])
    assert wired["harness"][0]["timeout_ms"] == 90000


async def test_artifacts_written(wired):
    cand = Candidate(run_id="claude_primary", run_name="claude_primary", task_id="P1", project_name="rsc", condition="floor", index=2)
    await orch.run_one_candidate(cand, timeouts={}, llm_call_factory=wired["llm_factory"])

    out = wired["artifacts_root"] / "claude_primary" / "P1__floor__n2"
    for fname in ("prompt.txt", "response.txt", "diff.patch", "harness_output.json", "metadata.json"):
        assert (out / fname).exists(), f"missing {fname}"

    meta = json.loads((out / "metadata.json").read_text())
    assert meta["model_id"] == "test-model"
    assert meta["condition"] == "floor"
    assert meta["stage"] == "test_pass"
    assert meta["mock"] is True
    # harness stage propagated into the artifact
    harness = json.loads((out / "harness_output.json").read_text())
    assert harness["stage"] == "test_pass"


async def test_mock_retrieval_skips_kg(wired):
    cand = Candidate(run_id="claude_primary", run_name="claude_primary", task_id="P1", project_name="rsc", condition="kg_augmented", index=1)
    await orch.run_one_candidate(cand, timeouts={}, llm_call_factory=wired["llm_factory"], mock_retrieval=True)
    # kg_augmented under mock_retrieval → empty context, no KG resolution used.
    assert "## CONTEXT BLOCK" not in wired["gen"][0]["prompt"]


async def test_temperature_guard_rejects_nonzero(wired, monkeypatch):
    def bad_cfg(run_name, condition_name, *a, **k):
        run = RunConfig(
            run_id=run_name, model_id="m", model_provider="test", temperature=0.7, max_tokens=10
        )
        condition = RetrievalConditionConfig(
            condition_id=condition_name, retriever=condition_name
        )
        return ExperimentConfig(run=run, condition=condition)

    monkeypatch.setattr(orch, "load_experiment_config", bad_cfg)
    cand = Candidate(run_id="r", run_name="r", task_id="P1", project_name="rsc", condition="floor", index=1)
    with pytest.raises(ValueError, match="temperature"):
        await orch.run_one_candidate(cand, timeouts={}, llm_call_factory=wired["llm_factory"])


# --------------------------------------------------------------------------- #
# Run-id override and the collision guard                                     #
# --------------------------------------------------------------------------- #
class TestRunIdGuard:
    """Output directories are keyed on run_id across all three artifact roots.

    Re-running under a populated run_id is the append-mode hazard: `results.jsonl`
    opens in append mode so rows land underneath the previous run's and every
    stage count silently doubles, while the per-candidate JSONs (keyed on
    candidate_id) are overwritten in place. The directory then holds two runs'
    rows and one run's artifacts, and nothing says so.
    """

    @staticmethod
    def _roots(tmp_path, monkeypatch):
        """Point all three artifact roots at a tmp dir."""
        monkeypatch.setattr(orch, "ARTIFACTS_ROOT", tmp_path / "candidate_artifacts")
        settings = orch.get_settings()
        monkeypatch.setattr(
            settings.harness, "results_dir", str(tmp_path / "harness_results")
        )
        return tmp_path

    def test_all_three_roots_follow_the_run_id(self, tmp_path, monkeypatch):
        self._roots(tmp_path, monkeypatch)
        dirs = orch._run_output_dirs("my_leg", log_dir=tmp_path / "experiment_logs")
        assert [d.name for d in dirs] == ["my_leg"] * 3
        assert {d.parent.name for d in dirs} == {
            "harness_results",
            "candidate_artifacts",
            "experiment_logs",
        }

    def test_free_run_id_passes(self, tmp_path, monkeypatch):
        self._roots(tmp_path, monkeypatch)
        orch._check_run_id_available("fresh_leg", log_dir=tmp_path / "experiment_logs")

    def test_empty_directory_is_not_a_collision(self, tmp_path, monkeypatch):
        """An empty dir carries no rows to append underneath."""
        self._roots(tmp_path, monkeypatch)
        (tmp_path / "harness_results" / "leg").mkdir(parents=True)
        orch._check_run_id_available("leg", log_dir=tmp_path / "experiment_logs")

    @pytest.mark.parametrize(
        "root", ["harness_results", "candidate_artifacts", "experiment_logs"]
    )
    def test_populated_directory_raises(self, tmp_path, monkeypatch, root):
        """Any one of the three roots is enough — artifacts and rows go stale
        independently."""
        self._roots(tmp_path, monkeypatch)
        occupied = tmp_path / root / "leg"
        occupied.mkdir(parents=True)
        (occupied / "results.jsonl").write_text("{}\n")
        with pytest.raises(orch.RunIdInUseError) as exc:
            orch._check_run_id_available("leg", log_dir=tmp_path / "experiment_logs")
        assert root in str(exc.value)

    def test_error_says_rename_not_delete(self, tmp_path, monkeypatch):
        """An archived leg is usually the only measurement of some earlier
        configuration — the 2026-07-23 unified_diff leg is exactly that."""
        self._roots(tmp_path, monkeypatch)
        occupied = tmp_path / "harness_results" / "leg"
        occupied.mkdir(parents=True)
        (occupied / "results.jsonl").write_text("{}\n")
        with pytest.raises(orch.RunIdInUseError, match="Rename"):
            orch._check_run_id_available("leg", log_dir=tmp_path / "experiment_logs")

    @pytest.mark.parametrize("bad", ["a/b", "..", ".", "", "a\\b"])
    def test_run_id_must_be_a_single_directory_name(self, bad, tmp_path, monkeypatch):
        """run_id becomes a directory name; a path would write outside the roots."""
        self._roots(tmp_path, monkeypatch)
        with pytest.raises(ValueError):
            orch._check_run_id_available(bad, log_dir=tmp_path / "experiment_logs")

    def test_candidates_carry_the_overridden_run_id(self):
        """Artifacts, logs and harness rows are all written under cand.run_id."""
        cands = build_candidates("claude_primary", run_id="claude_primary_reeval", n=1)
        assert {c.run_id for c in cands} == {"claude_primary_reeval"}
        # run_name still identifies the config the leg was run from.
        assert {c.run_name for c in cands} == {"claude_primary"}
