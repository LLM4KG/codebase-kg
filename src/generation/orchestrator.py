"""Pilot orchestrator: the per-candidate pipeline and the project-grouped run loop.

Per candidate: load config -> build retriever (floor | whole_file | bm25 |
text_emb_3_large | kg_augmented) -> retrieve()
-> generate diff -> run_candidate (harness) -> write artifacts. Candidates are
grouped by project so each project's KG is loaded once (one-project-per-DB), and
run under a small concurrency bound. A per-candidate failure is recorded, never
fatal to the run.

Mock modes (offline, zero-token, no keys):
  - `mock=True`          : mock generator returns the task's reference diff.
  - `mock_retrieval=True`: kg_augmented returns empty context (skips Memgraph +
                           the classifier LLM call). `mock` + `mock_retrieval`
                           together give a fully offline 40-candidate dry run.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml
from tenacity import RetryError

from src.config import get_settings
from src.generation.generator import generate_candidate_diff
from src.generation.kg_loader import ensure_project_kg_loaded, resolve_project_id
from src.generation.reference_edits import render_reference_response
from src.generation.edit_formats import EditScript
from src.harness.models import HarnessResult, HarnessStage
from src.harness.results import _write_harness_result
from src.harness.runner import QUARANTINED_MODES, run_candidate
from src.harness.tasks import load_pilot_task
from src.llm.logger import LLMResponse, UpstreamProviderError, _write_log_record
from src.retrieval.bm25_retriever import BM25Retriever
from src.retrieval.config import RetrievalConditionConfig, load_experiment_config
from src.retrieval.dense_retriever import DenseRetriever
from src.retrieval.floor_retriever import FloorRetriever
from src.retrieval.kg_retriever import KGAugmentedRetriever
from src.retrieval.whole_file_retriever import WholeFileRetriever

logger = logging.getLogger(__name__)

TASKS_DIR = Path("tasks/pilot")
ARTIFACTS_ROOT = Path("candidate_artifacts")
TIMEOUTS_TOML = Path("conditions/timeouts.toml")

# Conditions a pilot leg runs by default. `whole_file` joined the default set
# with the output-format work: the pilot's only non-KG arm was `floor`, whose
# prompt carries no source code, so it could never reach build or test. Every
# comparison was therefore KG-augmented against something that had already lost
# at the apply stage. `whole_file` is the cheapest arm that actually gets there.
CONDITIONS = ("floor", "whole_file", "kg_augmented")

# Everything `--conditions` will accept, including combinations that are not the
# default (e.g. re-running the original two-arm pilot shape).
# `bm25` (WP2) and `text_emb_3_large` (WP3, dense) are runnable but not defaults,
# so existing legs keep their shape.
# `bm25_matched` / `text_emb_3_large_matched` (WP12) are the same two retrievers
# capped at the KG's own per-task context instead of 7,000 tokens — an ablation
# that isolates selection quality from budget, not a sixth and seventh baseline,
# so they are opt-in like the two they are matched against.
KNOWN_CONDITIONS = ("floor", "whole_file", "kg_augmented", "bm25", "text_emb_3_large",
                    "kg_augmented_hardened", "bm25_matched", "text_emb_3_large_matched")

# Dispatch keys on the condition TOML's `retriever` field, never on the condition
# id (WP12). A condition is a *configuration* — `kg_augmented_hardened` and
# `bm25_matched` differ from their parents only in `[retriever_params]` — so the
# retriever is what the id resolves to, not what it is. Keying on the id meant a
# name tuple per retriever family (`KG_CONDITIONS` was the first) that had to be
# kept in sync with conditions/base/*.toml by hand; keying on the field means a
# new condition needs a TOML and nothing else.

# Which tasks each run exercises (WI4 run structure).
#
# The open-model leg ran P1 only through 2026-07-23 — and P1 was the one task
# whose KG-augmented arm was expected-fail by construction (no `Custom_Hook`
# nodes, so `bug_fix.cypher` returned nothing). That leg therefore validated
# multi-provider plumbing and nothing about open-model code generation. Widened
# to the full task set for the 2026-07-30 re-evaluation so both model families
# are measured on the same three tasks. P4-P6 added for the IJCKG 2026 revision
# (WP4, validated and calibrated 19 Sep); select a subset with `--tasks`.
RUN_TASKS: dict[str, list[str]] = {
    "claude_primary": ["P1", "P2", "P3", "P4", "P5", "P6"],   # 6 tasks x 3 conditions x n5 = 90
    "qwen_robustness": ["P1", "P2", "P3", "P4", "P5", "P6"],  # open-model leg: same shape = 90
}

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib


# --------------------------------------------------------------------------- #
# Task-spec / repo helpers (PilotTask has no `spec`/`reference_patch` field)   #
# --------------------------------------------------------------------------- #
def _load_task_yaml(task_id: str) -> dict:
    with open(TASKS_DIR / f"{task_id}.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_task_spec(task_id: str) -> str:
    spec = _load_task_yaml(task_id).get("spec")
    if not spec:
        raise ValueError(f"Task {task_id} has no 'spec' field")
    return spec.strip()


def load_reference_diff(task_id: str) -> str:
    ref = _load_task_yaml(task_id).get("reference_patch")
    if not ref:
        raise ValueError(f"Task {task_id} has no 'reference_patch' field")
    return (TASKS_DIR / ref).read_text(encoding="utf-8")


def resolve_repo_root(project_name: str) -> Path:
    settings = get_settings()
    cfg = settings.projects.get(project_name)
    if cfg is None:
        raise ValueError(f"No [projects.{project_name}] in pipeline.toml")
    return settings.resolve_repo_path(cfg.repo_path)


def _task_project(task_id: str) -> str:
    return load_pilot_task(task_id).project_id


def load_timeouts() -> dict[str, int]:
    """Load calibrated per-task timeouts (ms). Empty if not yet calibrated."""
    if not TIMEOUTS_TOML.exists():
        return {}
    with open(TIMEOUTS_TOML, "rb") as f:
        data = tomllib.load(f)
    return {str(k): int(v) for k, v in data.get("timeouts", {}).items()}


# --------------------------------------------------------------------------- #
# Candidate matrix                                                            #
# --------------------------------------------------------------------------- #
@dataclass
class Candidate:
    run_id: str
    run_name: str
    task_id: str
    project_name: str
    condition: str
    index: int
    candidate_id: str = field(default="")

    def __post_init__(self) -> None:
        if not self.candidate_id:
            self.candidate_id = f"{self.task_id}__{self.condition}__n{self.index}"


def build_candidates(
    run_name: str,
    *,
    run_id: str | None = None,
    n: int = 5,
    conditions=CONDITIONS,
    tasks: tuple[str, ...] | None = None,
) -> list[Candidate]:
    """`tasks` narrows the run's task list (e.g. re-running P2 after a retriever
    change); it may only name tasks the run config already covers."""
    if run_name not in RUN_TASKS:
        raise ValueError(f"Unknown run {run_name!r}. Known: {list(RUN_TASKS)}")
    task_ids = RUN_TASKS[run_name]
    if tasks:
        unknown = [t for t in tasks if t not in task_ids]
        if unknown:
            raise ValueError(
                f"Task(s) {unknown} not in run {run_name!r}. Known: {task_ids}"
            )
        task_ids = [t for t in task_ids if t in tasks]
    rid = run_id or run_name
    out: list[Candidate] = []
    for task_id in task_ids:
        project = _task_project(task_id)
        for condition in conditions:
            for i in range(1, n + 1):
                out.append(
                    Candidate(
                        run_id=rid,
                        run_name=run_name,
                        task_id=task_id,
                        project_name=project,
                        condition=condition,
                        index=i,
                    )
                )
    return out


# --------------------------------------------------------------------------- #
# Mock generator (offline dry run)                                            #
# --------------------------------------------------------------------------- #
def make_mock_llm_call(
    task_id: str,
    *,
    output_format: str = "unified_diff",
    repo_root: Path | None = None,
) -> Callable[..., Any]:
    """A drop-in for `logged_llm_call` returning the task's reference edit.

    Exercises the real extractor + real applier + real harness with zero tokens /
    no keys, in whichever format the run selects — so a format's plumbing can be
    proved before any of it is paid for. Still writes a JSONL log record so the
    "every LLM call is logged" invariant holds in dry runs.
    """
    ref_diff = load_reference_diff(task_id).rstrip("\n")
    canned_text = render_reference_response(
        ref_diff, output_format, repo_root or Path(".")
    )

    async def _mock(
        messages,
        *,
        model,
        run_id,
        condition_id,
        call_purpose,
        temperature=0.0,
        max_tokens=4096,
        log_dir=None,
        **_kw,
    ) -> LLMResponse:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model_id": model,
            "model_provider": "mock",
            "model_version": f"mock:{model}",
            "params": {"temperature": temperature, "max_tokens": max_tokens},
            "prompt": messages,
            "response": canned_text,
            "usage": {"input_tokens": 0, "output_tokens": 0},
            "call_purpose": call_purpose,
            "latency_ms": 0.0,
            "condition_id": condition_id,
            "run_id": run_id,
            "mock": True,
        }
        _write_log_record(record, run_id, condition_id, log_dir=log_dir)
        return LLMResponse(
            text=canned_text,
            usage={"input_tokens": 0, "output_tokens": 0},
            model_id=model,
            latency_ms=0.0,
        )

    return _mock


# --------------------------------------------------------------------------- #
# Per-candidate artifacts                                                     #
# --------------------------------------------------------------------------- #
def _write_candidate_artifacts(
    cand: Candidate,
    *,
    model_id: str,
    prompt: str,
    response_text: str,
    diff: str,
    harness: HarnessResult,
    retrieval_tokens: int,
    generator_usage: dict | None,
    generator_latency_ms: float,
    mock: bool,
    output_format: str = "unified_diff",
    script: EditScript | None = None,
    retrieval_metadata: dict | None = None,
) -> None:
    out = ARTIFACTS_ROOT / cand.run_id / cand.candidate_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "prompt.txt").write_text(prompt, encoding="utf-8")
    (out / "response.txt").write_text(response_text, encoding="utf-8")
    # Keeps its name across all three formats: for `unified_diff` it is the raw
    # patch, otherwise the JSON edit script the container applied. One filename
    # so the gate-review script and every existing consumer keep working.
    (out / "diff.patch").write_text(diff, encoding="utf-8")
    (out / "harness_output.json").write_text(
        harness.model_dump_json(indent=2), encoding="utf-8"
    )
    metadata = {
        "candidate_id": cand.candidate_id,
        "run_id": cand.run_id,
        "run_name": cand.run_name,
        "task_id": cand.task_id,
        "project_name": cand.project_name,
        "condition": cand.condition,
        "index": cand.index,
        "model_id": model_id,
        "stage": harness.stage.value,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "retrieval_token_count": retrieval_tokens,
        "generator_usage": generator_usage,
        "generator_latency_ms": generator_latency_ms,
        "mock": mock,
        "output_format": output_format,
        "apply_mode": harness.apply_mode,
        "apply_reason": harness.apply_reason,
        # Parse-side counts, distinct from the apply-side outcome: how many edits
        # the model expressed and how many attempts were unreadable. A format
        # comparison needs to separate "the model wrote nothing usable" from "it
        # wrote something the repo rejected".
        "edit_count": len(script.edits) if script else 0,
        "malformed_blocks": script.malformed_blocks if script else 0,
        "elided": script.elided if script else False,
        # What the retriever chose and why (BM25's ranking, KG's anchors). Additive:
        # before WP2 no retriever's metadata was persisted, so BM25's ranking — the
        # only record of how its context was picked — would have been lost.
        "retrieval_metadata": retrieval_metadata or {},
    }
    (out / "metadata.json").write_text(
        json.dumps(metadata, indent=2, default=str), encoding="utf-8"
    )


def _matched_token_budget(
    condition: RetrievalConditionConfig, task_id: str
) -> dict[str, int]:
    """`{"token_budget": n}` for a context-budget-matched condition, else `{}`.

    A condition that declares `[retriever_params] token_budget_by_task` (WP12's
    `*_matched` ablation arms) must declare it for *every* task it runs: a missing
    entry raises rather than falling back to the retriever's 7,000-token default.
    An arm named "matched" that silently ran at 7,000 tokens would be WP8's
    silent-floor defect in a new costume — a condition labelled one thing and
    behaving as another, invisible everywhere but in a token count. The budgets are
    generated from wp5_outcomes.csv for all six tasks, so this is a guard, not a
    code path.
    """
    by_task = condition.retriever_params.get("token_budget_by_task")
    if by_task is None:
        return {}
    budget = by_task.get(task_id)
    if budget is None:
        raise ValueError(
            f"condition {condition.condition_id!r} sets token_budget_by_task but has no "
            f"entry for {task_id} — refusing to run it at the default budget, which "
            f"would record an unmatched candidate under a matched condition. Add "
            f"{task_id} to conditions/base/{condition.condition_id}.toml."
        )
    return {"token_budget": int(budget)}


# --------------------------------------------------------------------------- #
# Per-candidate pipeline                                                      #
# --------------------------------------------------------------------------- #
async def run_one_candidate(
    cand: Candidate,
    *,
    timeouts: dict[str, int],
    log_dir: Path | None = None,
    llm_call_factory: Callable[[Candidate], Callable[..., Any]] | None = None,
    mock_retrieval: bool = False,
    output_format: str | None = None,
) -> HarnessResult:
    cfg = load_experiment_config(cand.run_name, cand.condition)
    if output_format is not None:
        # CLI override, for the format head-to-head. Applied to the RunConfig so
        # the generator, the artifacts and the harness all see one value — the
        # format must never differ between the prompt and the applier.
        cfg = cfg.model_copy(
            update={"run": cfg.run.model_copy(update={"output_format": output_format})}
        )
    if cfg.run.temperature != 0.0:
        raise ValueError(
            f"Run {cand.run_name!r} temperature={cfg.run.temperature} — must be 0.0 (D-LLM1)"
        )
    spec = load_task_spec(cand.task_id)
    repo_root = resolve_repo_root(cand.project_name)
    # The TOML's `retriever`, not the condition id: see the note above KNOWN_CONDITIONS.
    retriever_name = cfg.condition.retriever

    if retriever_name == "kg_augmented" and not mock_retrieval:
        project_id = resolve_project_id(cand.project_name)
        retriever = KGAugmentedRetriever(
            cfg.condition,
            model=cfg.run.model_id,
            run_id=cand.run_id,
            project_name=cand.project_name,
            log_dir=log_dir,
        )
        result = await retriever.retrieve(spec, project_id, repo_root)
    elif retriever_name == "whole_file":
        # Oracle localisation from the frozen task YAML — no KG, no LLM, so
        # `--mock-retrieval` has nothing to skip and this arm stays real in a
        # dry run.
        result = await WholeFileRetriever(
            cfg.condition,
            task_id=cand.task_id,
            task_type=_load_task_yaml(cand.task_id).get("task_type", ""),
            project_name=cand.project_name,
        ).retrieve(spec, "", repo_root)
    elif retriever_name == "bm25":
        # Lexical baseline over the KG's own file set (same exclude_paths as
        # extraction), filled to the KG's token budget. No KG, no LLM.
        project_cfg = get_settings().projects.get(cand.project_name)
        result = await BM25Retriever(
            cfg.condition,
            task_type=_load_task_yaml(cand.task_id).get("task_type", ""),
            project_name=cand.project_name,
            exclude_paths=project_cfg.exclude_paths if project_cfg else [],
            **_matched_token_budget(cfg.condition, cand.task_id),
        ).retrieve(spec, "", repo_root)
    elif retriever_name == "text_emb_3_large":
        # Dense baseline: BM25's corpus and fill, scored by embedding cosine. No KG
        # and no generator-side LLM; embeddings come from the committed cache or an
        # OpenAI call logged under this run. Stays real under --mock-retrieval.
        project_cfg = get_settings().projects.get(cand.project_name)
        result = await DenseRetriever(
            cfg.condition,
            run_id=cand.run_id,
            task_type=_load_task_yaml(cand.task_id).get("task_type", ""),
            project_name=cand.project_name,
            exclude_paths=project_cfg.exclude_paths if project_cfg else [],
            log_dir=log_dir,
            **_matched_token_budget(cfg.condition, cand.task_id),
        ).retrieve(spec, "", repo_root)
    elif retriever_name in ("floor", "kg_augmented"):
        # floor, or a KG arm under --mock-retrieval: empty context, no KG/LLM.
        result = await FloorRetriever(cfg.condition).retrieve(spec, "", repo_root)
    else:
        # Never fall through to the floor. A condition with no branch here used to
        # run silently as floor and be reported as itself — a condition whose TOML
        # loads but whose retriever is missing would have produced a whole arm of
        # empty-context candidates with no trace of the mistake (WP8/WP12).
        raise ValueError(
            f"no retriever is wired for condition {cand.condition!r} "
            f"(retriever={retriever_name!r}); add a branch in run_one_candidate, or fix "
            f"`retriever` in conditions/base/{cand.condition}.toml, or remove the "
            f"condition from KNOWN_CONDITIONS"
        )

    context_block = result.context

    llm_call = llm_call_factory(cand) if llm_call_factory else None
    gen_kwargs: dict[str, Any] = dict(
        spec=spec,
        context_block=context_block,
        run=cfg.run,
        condition_id=cfg.condition.condition_id,
        run_id=cand.run_id,
        log_dir=log_dir,
    )
    if llm_call is not None:
        gen_kwargs["llm_call"] = llm_call
    gen = await generate_candidate_diff(**gen_kwargs)

    harness = await run_candidate(
        candidate_diff=gen.diff,
        task=load_pilot_task(cand.task_id),
        condition=cand.condition,
        model=cfg.run.model_id,
        candidate_id=cand.candidate_id,
        run_id=cand.run_id,
        timeout_ms=timeouts.get(cand.task_id),
        output_format=cfg.run.output_format,
    )

    _write_candidate_artifacts(
        cand,
        model_id=cfg.run.model_id,
        prompt=gen.prompt,
        response_text=gen.response_text,
        diff=gen.diff,
        harness=harness,
        retrieval_tokens=result.total_token_count,
        retrieval_metadata=result.metadata,
        generator_usage=gen.usage,
        generator_latency_ms=gen.latency_ms,
        mock=llm_call is not None,
        output_format=cfg.run.output_format,
        script=gen.script,
    )
    return harness


def _failure_detail(exc: Exception) -> str:
    """Human-readable cause for an orchestrator-side failure.

    Unwraps tenacity's RetryError, which otherwise reports only
    `RetryError[<Future ... raised APIConnectionError>]` and discards the
    underlying cause entirely.
    """
    root: BaseException = exc
    if isinstance(root, RetryError) and root.last_attempt.failed:
        root = root.last_attempt.exception() or root

    if isinstance(root, UpstreamProviderError):
        return (
            f"{root}\n"
            f"provider={root.provider} status={root.status_code} model={root.model}\n"
            f"--- raw upstream payload ---\n{root.raw}"
        )
    return f"{type(root).__name__}: {root}"


def _record_failure(cand: Candidate, exc: Exception) -> HarnessResult:
    hr = HarnessResult(
        task_id=cand.task_id,
        candidate_id=cand.candidate_id,
        condition=cand.condition,
        model="",
        stage=HarnessStage.harness_error,
        exit_code=None,
        stdout="",
        stderr=f"orchestrator error: {exc}",
        duration_ms=0.0,
        timeout_used_ms=0,
        stage_detail=_failure_detail(exc),
    )
    _write_harness_result(hr, cand.run_id)
    return hr


# --------------------------------------------------------------------------- #
# Run loop                                                                    #
# --------------------------------------------------------------------------- #
class RunIdInUseError(RuntimeError):
    """A run's output directories already exist and hold a previous run."""


def _run_output_dirs(run_id: str, log_dir: Path | None = None) -> list[Path]:
    """The three roots every leg writes under, all keyed on run_id."""
    return [
        Path(get_settings().harness.results_dir) / run_id,
        ARTIFACTS_ROOT / run_id,
        (log_dir or Path(getattr(get_settings().pipeline, "experiment_log_dir", "experiment_logs")))
        / run_id,
    ]


def _check_run_id_available(run_id: str, log_dir: Path | None = None) -> None:
    """Refuse to write a leg into directories a previous run already populated.

    `results.jsonl` opens in append mode, so a second run under the same run_id
    lands its rows underneath the first and every stage count silently doubles;
    the per-candidate JSONs and artifacts, keyed on candidate_id, are overwritten
    in place, so a directory can end up holding two runs' rows and one run's
    artifacts. Both hazards are invisible until someone recomputes the counts.

    Renaming the old directory (never deleting — an archived leg is usually the
    only measurement of some earlier configuration) or choosing a new --run-id
    are the two ways forward.
    """
    if "/" in run_id or "\\" in run_id or run_id in {"", ".", ".."}:
        raise ValueError(
            f"run_id {run_id!r} must be a single directory name, not a path."
        )

    occupied = [d for d in _run_output_dirs(run_id, log_dir) if d.exists() and any(d.iterdir())]
    if occupied:
        listed = "\n  ".join(str(d) for d in occupied)
        raise RunIdInUseError(
            f"run_id {run_id!r} already has output:\n  {listed}\n"
            f"Rename those directories (keep them — they are the record of that leg) "
            f"or pass --run-id with a new name."
        )


async def run_pilot(
    run_name: str,
    *,
    n: int = 5,
    mock: bool = False,
    mock_retrieval: bool = False,
    concurrency: int = 2,
    log_dir: Path | None = None,
    output_format: str | None = None,
    conditions: tuple[str, ...] = CONDITIONS,
    run_id: str | None = None,
    tasks: tuple[str, ...] | None = None,
) -> list[HarnessResult]:
    """Run one leg of the pilot (all conditions x tasks x n). Returns the results.

    `run_id` overrides the config's run_id, which names the output directory under
    each of the three artifact roots. Every leg so far has been run under the
    config name and renamed afterwards; passing the archival name up front is
    both fewer steps and one less chance to append into a populated directory.
    """
    run_cfg = load_experiment_config(run_name, conditions[0]).run
    run_id = run_id or run_cfg.run_id
    _check_run_id_available(run_id, log_dir=log_dir)
    effective_format = output_format or run_cfg.output_format
    candidates = build_candidates(
        run_name, run_id=run_id, n=n, conditions=conditions, tasks=tasks
    )
    timeouts = load_timeouts()
    sem = asyncio.Semaphore(concurrency)

    def _mock_factory(cand: Candidate) -> Callable[..., Any]:
        return make_mock_llm_call(
            cand.task_id,
            output_format=effective_format,
            repo_root=resolve_repo_root(cand.project_name),
        )

    llm_call_factory = _mock_factory if mock else None

    async def _guarded(cand: Candidate) -> HarnessResult:
        async with sem:
            try:
                return await run_one_candidate(
                    cand,
                    timeouts=timeouts,
                    log_dir=log_dir,
                    llm_call_factory=llm_call_factory,
                    mock_retrieval=mock_retrieval,
                    output_format=output_format,
                )
            except Exception as exc:  # never abort the whole run
                logger.exception("Candidate %s failed", cand.candidate_id)
                return _record_failure(cand, exc)

    # Group by project so each project's KG is loaded once (one-project-per-DB).
    by_project: dict[str, list[Candidate]] = {}
    for c in candidates:
        by_project.setdefault(c.project_name, []).append(c)

    results: list[HarnessResult] = []
    for project, group in by_project.items():
        needs_kg = (not mock_retrieval) and any(
            load_experiment_config(c.run_name, c.condition).condition.retriever
            == "kg_augmented"
            for c in group
        )
        if needs_kg:
            ensure_project_kg_loaded(project)
        results.extend(await asyncio.gather(*[_guarded(c) for c in group]))

    _log_summary(run_id, results)
    return results


def _log_summary(run_id: str, results: list[HarnessResult]) -> None:
    by_condition: dict[str, Counter] = {}
    for r in results:
        by_condition.setdefault(r.condition, Counter())[r.stage.value] += 1
    logger.info("Pilot run %r — %d candidates", run_id, len(results))
    for r in results:
        if r.apply_mode in QUARANTINED_MODES:
            logger.warning(
                "  %s applied via %s — UNVERIFIED, quarantine at reporting time",
                r.candidate_id,
                r.apply_mode,
            )
    for condition, counts in by_condition.items():
        logger.info("  [%s] %s", condition, dict(counts))
