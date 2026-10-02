"""Unit tests for the per-candidate orchestration (LLM + harness + KG all mocked)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.generation import orchestrator as orch
from src.generation.orchestrator import Candidate, build_candidates
from src.harness.models import HarnessStage
from src.retrieval.models import RetrievalResult
from src.retrieval.config import (
    ExperimentConfig,
    RetrievalConditionConfig,
    RunConfig,
    load_condition_config,
)


# --------------------------------------------------------------------------- #
# Candidate matrix                                                            #
# --------------------------------------------------------------------------- #
def test_build_candidates_primary_is_90():
    """6 tasks x 3 conditions x n=5. `whole_file` joined the default set with the
    output-format work — it is the only non-KG arm that can reach build/test."""
    cands = build_candidates("claude_primary", n=5)
    assert len(cands) == 90
    assert len({c.candidate_id for c in cands}) == 90
    assert {c.condition for c in cands} == {"floor", "whole_file", "kg_augmented"}


def test_build_candidates_open_model_leg_matches_primary_shape():
    """The open-model leg ran P1 only until 2026-07-30. P1's KG arm was
    expected-fail by construction, so that leg measured plumbing, not code
    generation. Both legs now span the same six tasks (P4-P6 added in WP4)."""
    cands = build_candidates("qwen_robustness", n=5)
    assert len(cands) == 90
    assert {c.task_id for c in cands} == {"P1", "P2", "P3", "P4", "P5", "P6"}
    assert {c.condition for c in cands} == {"floor", "whole_file", "kg_augmented"}


def test_build_candidates_honours_explicit_conditions():
    """`--conditions` reproduces the original two-arm pilot shape."""
    cands = build_candidates("claude_primary", n=5, conditions=("floor", "kg_augmented"))
    assert len(cands) == 60
    assert {c.condition for c in cands} == {"floor", "kg_augmented"}


def test_build_candidates_task_subset():
    """`--tasks P2` re-runs one task after a retriever change without touching the rest."""
    cands = build_candidates("claude_primary", n=5, conditions=("kg_augmented",), tasks=("P2",))
    assert len(cands) == 5
    assert {c.task_id for c in cands} == {"P2"}


def test_build_candidates_rejects_task_outside_run():
    with pytest.raises(ValueError, match="not in run"):
        build_candidates("claude_primary", n=1, tasks=("P9",))


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


async def test_bm25_dispatches_and_persists_its_ranking(wired):
    """WP2: `bm25` builds its context from the repo on disk — no KG load, no
    classifier — and its ranking is kept in metadata.json."""
    repo = wired["artifacts_root"].parent / "rsc"   # resolve_repo_root -> tmp_path / name
    for rel, body in {
        "src/specHandler.ts": "export const spec = 'spec for the task'",
        "src/Header.tsx": "const Header = () => null",
        "src/Footer.tsx": "const Footer = () => null",
        "src/Logo.tsx": "const Logo = () => null",
    }.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(body)

    cand = Candidate(run_id="claude_primary", run_name="claude_primary", task_id="P1", project_name="rsc", condition="bm25", index=1)
    await orch.run_one_candidate(cand, timeouts={}, llm_call_factory=wired["llm_factory"])

    prompt = wired["gen"][0]["prompt"]
    assert "`src/specHandler.ts`" in prompt
    assert "Header" not in prompt
    assert wired["kg_loaded"] == [] and wired["retriever_model"] == []
    meta = json.loads((wired["artifacts_root"] / "claude_primary" / "P1__bm25__n1" / "metadata.json").read_text())
    assert meta["condition"] == "bm25"
    assert meta["retrieval_metadata"]["included_files"] == ["src/specHandler.ts"]
    assert meta["retrieval_token_count"] <= 7000


async def test_dense_dispatches_logs_its_embeddings_and_persists_its_ranking(wired, monkeypatch):
    """WP3: `text_emb_3_large` embeds the repo on disk (no KG load, no classifier),
    logs the embedding calls under the candidate's run, and keeps its ranking."""
    from types import SimpleNamespace

    from src.llm import logger as llm_logger
    from src.retrieval import dense_retriever

    tmp = wired["artifacts_root"].parent
    repo = tmp / "rsc"
    for rel, body in {
        "src/specHandler.ts": "export const spec = 'spec for the task'",
        "src/Header.tsx": "const Header = () => null",
    }.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(body)

    async def fake_aembedding(*, model, input):
        vec = lambda t: [1.0, 0.0] if "spec" in t else [0.0, 1.0]
        return SimpleNamespace(
            data=[{"index": i, "embedding": vec(t)} for i, t in enumerate(input)],
            usage=SimpleNamespace(prompt_tokens=7), model=model,
        )

    monkeypatch.setattr(llm_logger.litellm, "aembedding", fake_aembedding)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(dense_retriever, "DEFAULT_CACHE_ROOT", tmp / "embedding_cache")
    monkeypatch.setattr(llm_logger, "_get_log_dir", lambda: tmp / "logs")
    dense_retriever.build_corpus.cache_clear()

    cand = Candidate(run_id="claude_primary", run_name="claude_primary", task_id="P1", project_name="rsc", condition="text_emb_3_large", index=1)
    await orch.run_one_candidate(cand, timeouts={}, llm_call_factory=wired["llm_factory"])

    assert "`src/specHandler.ts`" in wired["gen"][0]["prompt"]
    assert wired["kg_loaded"] == [] and wired["retriever_model"] == []
    meta = json.loads((wired["artifacts_root"] / "claude_primary" / "P1__text_emb_3_large__n1" / "metadata.json").read_text())
    rmd = meta["retrieval_metadata"]
    assert rmd["ranked_top"][0]["path"] == "src/specHandler.ts"
    assert rmd["api_calls"] == 2
    assert meta["retrieval_token_count"] <= 7000
    assert (tmp / "embedding_cache" / "rsc" / "text-embedding-3-large.jsonl").exists()
    log = (tmp / "logs" / "claude_primary" / "text_emb_3_large.jsonl").read_text().splitlines()
    assert [json.loads(r)["call_purpose"] for r in log] == ["embedding_index", "embedding_query"]
    dense_retriever.build_corpus.cache_clear()


async def test_retrieval_metadata_defaults_to_empty(wired):
    cand = Candidate(run_id="claude_primary", run_name="claude_primary", task_id="P1", project_name="rsc", condition="floor", index=1)
    await orch.run_one_candidate(cand, timeouts={}, llm_call_factory=wired["llm_factory"])
    meta = json.loads((wired["artifacts_root"] / "claude_primary" / "P1__floor__n1" / "metadata.json").read_text())
    assert meta["retrieval_metadata"] == {}


def test_dense_is_known_but_not_a_default_condition():
    assert "text_emb_3_large" in orch.KNOWN_CONDITIONS
    assert "text_emb_3_large" not in orch.CONDITIONS


def test_bm25_is_known_but_not_a_default_condition():
    """Existing legs keep their three-condition shape; bm25 is opt-in."""
    assert "bm25" in orch.KNOWN_CONDITIONS
    assert "bm25" not in orch.CONDITIONS
    cands = build_candidates("claude_primary", n=1, conditions=("bm25",))
    assert {c.condition for c in cands} == {"bm25"}


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


# --------------------------------------------------------------------------- #
# Condition dispatch must never fall through to the floor (WP8/WP12)          #
# --------------------------------------------------------------------------- #
def test_hardened_kg_condition_is_known_but_not_a_default():
    assert "kg_augmented_hardened" in orch.KNOWN_CONDITIONS
    assert "kg_augmented_hardened" not in orch.CONDITIONS


def test_the_hardened_condition_toml_is_what_routes_it_to_the_kg_retriever():
    """WP8 shipped a `KG_CONDITIONS` name tuple; WP12 deleted it.

    What makes the hardened arm a KG arm is now its own TOML, which is also what
    makes it a *configuration* of kg_augmented rather than a second retriever.
    """
    assert not hasattr(orch, "KG_CONDITIONS")
    assert load_condition_config("kg_augmented_hardened").retriever == "kg_augmented"


async def test_hardened_kg_condition_dispatches_to_the_kg_retriever(wired):
    cand = Candidate(run_id="claude_primary", run_name="claude_primary", task_id="P1",
                     project_name="rsc", condition="kg_augmented_hardened", index=1)
    await orch.run_one_candidate(cand, timeouts={}, llm_call_factory=wired["llm_factory"])
    assert "## CONTEXT BLOCK" in wired["gen"][0]["prompt"]
    assert wired["kg_project_id"] == "HASH::rsc"


async def test_a_condition_with_no_retriever_raises_instead_of_running_as_floor(wired):
    """The dispatch chain used to end in `else: FloorRetriever(...)`.

    A condition whose TOML loaded but whose retriever branch was missing produced a
    whole arm of empty-context candidates, recorded under its own condition id, with
    nothing anywhere to say what had happened.
    """
    cand = Candidate(run_id="claude_primary", run_name="claude_primary", task_id="P1",
                     project_name="rsc", condition="not_a_real_condition", index=1)
    with pytest.raises(ValueError, match="no retriever is wired"):
        await orch.run_one_candidate(cand, timeouts={}, llm_call_factory=wired["llm_factory"])


# --------------------------------------------------------------------------- #
# Context-budget-matched ablation arms (WP12)                                 #
# --------------------------------------------------------------------------- #

# What each shipped condition dispatched to when dispatch matched the condition id
# (`kg_augmented_hardened` via WP8's `KG_CONDITIONS` tuple). WP12 rewrote the chain
# to read `retriever` from the TOML instead; if that field ever disagrees with this
# map, a published arm changed retriever without anyone saying so.
PRE_WP12_DISPATCH = {
    "floor": "floor",
    "whole_file": "whole_file",
    "kg_augmented": "kg_augmented",
    "kg_augmented_hardened": "kg_augmented",
    "bm25": "bm25",
    "text_emb_3_large": "text_emb_3_large",
    # Designed but never implemented (WP3 scope): nothing is wired for it, so it
    # raised before the keying change and must still raise after it.
    "nomic_embed_code": "nomic_embed_code",
}


@pytest.mark.parametrize("condition,retriever", sorted(PRE_WP12_DISPATCH.items()))
def test_every_shipped_condition_resolves_to_the_retriever_it_used_to_dispatch_to(
    condition, retriever
):
    assert load_condition_config(condition).retriever == retriever


def test_the_shipped_conditions_are_all_of_them():
    """The guard above is a regression guard only while it covers every condition
    that existed before WP12 — a new TOML must be added to it deliberately."""
    on_disk = {p.stem for p in Path("conditions/base").glob("*.toml")}
    added_by_wp12 = {"bm25_matched", "text_emb_3_large_matched"}
    assert on_disk - added_by_wp12 == set(PRE_WP12_DISPATCH)


def _recorder(name: str, calls: list):
    class _Recorded:
        def __init__(self, config, **kw):
            calls.append({"retriever": name, "condition_id": config.condition_id, **kw})
            self.config = config

        async def retrieve(self, spec, project_id, repo_root, max_rounds=1):
            return RetrievalResult(
                context="## CONTEXT BLOCK",
                rounds=[],
                retriever_name=name,
                condition_id=self.config.condition_id,
                total_token_count=1,
            )

    return _Recorded


@pytest.fixture
def dispatched(wired, monkeypatch):
    """Every retriever class replaced by a recorder; yields what got constructed."""
    calls: list = []
    for attr, name in [
        ("FloorRetriever", "floor"),
        ("WholeFileRetriever", "whole_file"),
        ("BM25Retriever", "bm25"),
        ("DenseRetriever", "text_emb_3_large"),
        ("KGAugmentedRetriever", "kg_augmented"),
    ]:
        monkeypatch.setattr(orch, attr, _recorder(name, calls))
    monkeypatch.setattr(orch, "_load_task_yaml", lambda tid: {"task_type": "bug_fix"})
    return calls


@pytest.mark.parametrize(
    "condition,retriever",
    [
        ("floor", "floor"),
        ("whole_file", "whole_file"),
        ("kg_augmented", "kg_augmented"),
        ("kg_augmented_hardened", "kg_augmented"),
        ("bm25", "bm25"),
        ("text_emb_3_large", "text_emb_3_large"),
        ("bm25_matched", "bm25"),
        ("text_emb_3_large_matched", "text_emb_3_large"),
    ],
)
async def test_dispatch_routes_on_the_toml_retriever_not_the_condition_id(
    condition, retriever, wired, dispatched
):
    """Four of these eight conditions share a retriever with another.

    Before WP12 the chain matched condition ids, so every id needed its own branch
    or a name tuple; now `bm25_matched` reaches BM25Retriever because its TOML says
    `retriever = "bm25"` and for no other reason.
    """
    cand = Candidate(run_id="claude_primary", run_name="claude_primary", task_id="P1",
                     project_name="rsc", condition=condition, index=1)
    await orch.run_one_candidate(cand, timeouts={}, llm_call_factory=wired["llm_factory"])

    assert [c["retriever"] for c in dispatched] == [retriever]
    assert dispatched[0]["condition_id"] == condition


@pytest.mark.parametrize("task,budget", [("P1", 626), ("P2", 1532), ("P3", 772)])
@pytest.mark.parametrize("condition", ["bm25_matched", "text_emb_3_large_matched"])
async def test_a_matched_arm_is_capped_at_that_tasks_kg_context(
    condition, task, budget, wired, dispatched
):
    cand = Candidate(run_id="claude_primary", run_name="claude_primary", task_id=task,
                     project_name="rsc", condition=condition, index=1)
    await orch.run_one_candidate(cand, timeouts={}, llm_call_factory=wired["llm_factory"])
    assert dispatched[0]["token_budget"] == budget


@pytest.mark.parametrize("condition", ["bm25", "text_emb_3_large"])
async def test_the_published_arms_are_still_run_at_the_retriever_default(
    condition, wired, dispatched
):
    """The ablation must not reach the 7,000-token arms it is matched against."""
    cand = Candidate(run_id="claude_primary", run_name="claude_primary", task_id="P1",
                     project_name="rsc", condition=condition, index=1)
    await orch.run_one_candidate(cand, timeouts={}, llm_call_factory=wired["llm_factory"])
    assert "token_budget" not in dispatched[0]


async def test_a_matched_arm_missing_the_task_raises_instead_of_running_at_7000(
    wired, dispatched
):
    """WP8's silent-floor defect in a new costume.

    A candidate recorded under `bm25_matched` that had actually run at the default
    budget would be an arm labelled one thing and behaving as another — invisible
    in every artifact except a token count nobody reads per candidate. The budget
    table is generated for all six tasks, so this is a guard, not a code path.
    """
    cand = Candidate(run_id="claude_primary", run_name="claude_primary", task_id="P6",
                     project_name="rsc", condition="bm25_matched", index=1)
    with pytest.raises(ValueError, match="no entry for P6"):
        await orch.run_one_candidate(cand, timeouts={}, llm_call_factory=wired["llm_factory"])
    assert dispatched == []


def test_the_matched_conditions_are_known_but_not_defaults():
    for c in ("bm25_matched", "text_emb_3_large_matched"):
        assert c in orch.KNOWN_CONDITIONS
        assert c not in orch.CONDITIONS
    cands = build_candidates("claude_primary", n=1, conditions=("bm25_matched",))
    assert {c.condition for c in cands} == {"bm25_matched"}


async def test_a_matched_arm_really_drops_files_a_7000_token_arm_would_keep(wired):
    """The recorder tests prove the number is passed; this proves it binds.

    Uses the real BM25Retriever against a repo whose matching files total far more
    than P1's 626-token budget.
    """
    repo = wired["artifacts_root"].parent / "rsc"
    for i in range(40):
        p = repo / "src" / f"cart{i}.ts"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("export const spec = 'spec for the task ' + " + " + ".join(["'x'"] * 40))

    async def one(condition):
        cand = Candidate(run_id="claude_primary", run_name="claude_primary", task_id="P1",
                         project_name="rsc", condition=condition, index=1)
        await orch.run_one_candidate(cand, timeouts={}, llm_call_factory=wired["llm_factory"])
        out = wired["artifacts_root"] / "claude_primary" / f"P1__{condition}__n1"
        return json.loads((out / "metadata.json").read_text())

    matched = await one("bm25_matched")
    unmatched = await one("bm25")

    assert matched["retrieval_metadata"]["token_budget"] == 626
    assert matched["retrieval_token_count"] <= 626
    assert unmatched["retrieval_metadata"]["token_budget"] == 7000
    kept_matched = len(matched["retrieval_metadata"]["included_files"])
    kept_unmatched = len(unmatched["retrieval_metadata"]["included_files"])
    assert 0 < kept_matched < kept_unmatched == 40
