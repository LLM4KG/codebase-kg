"""Shared fakes for the generation-side unit tests.

The `wired` fixture monkeypatches the orchestrator's external collaborators —
LLM, KG, Docker harness — and records what each was handed. It lives in a
conftest because both the orchestration tests and the output-format axis tests
need the same seam: one asserts the pipeline routes correctly, the other that a
single format value reaches both ends of it.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.generation import orchestrator as orch
from src.harness.models import HarnessResult, HarnessStage
from src.llm.logger import LLMResponse
from src.retrieval.config import ExperimentConfig, RetrievalConditionConfig, RunConfig
from src.retrieval.models import RetrievalResult


# Conditions whose `retriever` is not their own id, mirroring conditions/base/*.toml.
# The orchestrator dispatches on the field (WP12), so a fake that assumed
# retriever == condition_id would make `kg_augmented_hardened` resolve to a
# retriever nothing is wired for and raise — a failure in the stand-in that reads
# exactly like a broken KG arm. Everything absent here is its own retriever.
CONDITION_RETRIEVERS = {
    "kg_augmented_hardened": "kg_augmented",
    "bm25_matched": "bm25",
    "text_emb_3_large_matched": "text_emb_3_large",
}

# Per-task context budgets for the WP12 matched arms, as the generated TOMLs carry
# them. Only the tasks the generation tests use need to be here.
RETRIEVER_PARAMS = {
    "bm25_matched": {"token_budget_by_task": {"P1": 626, "P2": 1532, "P3": 772}},
    "text_emb_3_large_matched": {
        "embedding_model": "text-embedding-3-large",
        "token_budget_by_task": {"P1": 626, "P2": 1532, "P3": 772},
    },
}


# --------------------------------------------------------------------------- #
# Shared fixtures / fakes                                                     #
# --------------------------------------------------------------------------- #
@pytest.fixture
def wired(monkeypatch, tmp_path):
    """Monkeypatch the orchestrator's external collaborators; capture their calls."""
    calls: dict = {"gen": [], "harness": [], "kg_loaded": [], "retriever_model": []}

    def fake_load_experiment_config(run_name, condition_name, *a, **k):
        # Real config models, not SimpleNamespace: the orchestrator's
        # `--output-format` override goes through `model_copy`, and the
        # generator reads `run.output_format` — a stand-in that happens to have
        # the right attributes would pass while the real path was broken.
        run = RunConfig(
            run_id=run_name,
            model_id="test-model",
            model_provider="test",
            temperature=0.0,
            max_tokens=4096,
        )
        condition = RetrievalConditionConfig(
            condition_id=condition_name,
            retriever=CONDITION_RETRIEVERS.get(condition_name, condition_name),
            format_variant="A",
            retriever_params=dict(RETRIEVER_PARAMS.get(condition_name, {})),
        )
        return ExperimentConfig(run=run, condition=condition)

    class FakeKGRetriever:
        def __init__(self, config, *, model, run_id, project_name="", log_dir=None):
            calls["retriever_model"].append(model)
            self.config = config

        async def retrieve(self, spec, project_id, repo_root, max_rounds=1):
            calls["kg_project_id"] = project_id
            return RetrievalResult(
                context="## CONTEXT BLOCK",
                rounds=[],
                retriever_name="kg_augmented",
                condition_id=self.config.condition_id,
                total_token_count=42,
            )

    async def fake_run_candidate(*, candidate_diff, task, condition, model, candidate_id, run_id, timeout_ms=None, output_format="unified_diff", **kw):
        calls["harness"].append(
            dict(
                diff=candidate_diff,
                condition=condition,
                model=model,
                candidate_id=candidate_id,
                timeout_ms=timeout_ms,
                output_format=output_format,
            )
        )
        return HarnessResult(
            task_id=getattr(task, "task_id", "P1"),
            candidate_id=candidate_id,
            condition=condition,
            model=model,
            stage=HarnessStage.test_pass,
            exit_code=0,
            stdout="",
            stderr="",
            duration_ms=123.0,
            timeout_used_ms=timeout_ms or 60000,
        )

    monkeypatch.setattr(orch, "load_experiment_config", fake_load_experiment_config)
    monkeypatch.setattr(orch, "KGAugmentedRetriever", FakeKGRetriever)
    monkeypatch.setattr(orch, "run_candidate", fake_run_candidate)
    monkeypatch.setattr(orch, "resolve_project_id", lambda name: f"HASH::{name}")
    monkeypatch.setattr(orch, "ensure_project_kg_loaded", lambda name: calls["kg_loaded"].append(name))
    monkeypatch.setattr(orch, "load_task_spec", lambda tid: f"spec for {tid}")
    monkeypatch.setattr(orch, "resolve_repo_root", lambda name: tmp_path / name)
    monkeypatch.setattr(orch, "load_pilot_task", lambda tid: SimpleNamespace(task_id=tid, project_id="proj"))
    monkeypatch.setattr(orch, "ARTIFACTS_ROOT", tmp_path / "artifacts")

    def recording_llm_factory(cand):
        async def _rec(messages, *, model, run_id, condition_id, call_purpose, temperature=0.0, max_tokens=4096, log_dir=None, **kw):
            calls["gen"].append(
                dict(model=model, call_purpose=call_purpose, temperature=temperature, condition_id=condition_id, prompt=messages[0]["content"])
            )
            return LLMResponse(text="```diff\ndiff --git a/x b/x\n@@ -1 +1 @@\n-a\n+b\n```", usage=None, model_id=model, latency_ms=0.0)
        return _rec

    calls["llm_factory"] = recording_llm_factory
    calls["artifacts_root"] = tmp_path / "artifacts"
    return calls
