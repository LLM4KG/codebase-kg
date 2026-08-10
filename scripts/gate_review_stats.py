#!/usr/bin/env python3
"""Re-derive every number quoted in the Phase 1a gate review, from disk only.

This script deliberately reads *no* prose document. It recomputes the pilot's
stage distributions, per-condition arithmetic, artifact completeness, retrieval
token counts, LLM call decomposition and reference-patch timings straight from
the run artifacts, so the gate review can cite computed values rather than
restating the checklist it is supposed to be verifying.

Run directories are arguments, not constants. The first version of this script
hardcoded `claude_primary` / `qwen_robustness`; when those legs were archived
under dated names the script stopped running at all, which is precisely the
failure mode a reproducibility tool must not have.

Usage:
    python3 scripts/gate_review_stats.py                      # the two current legs
    python3 scripts/gate_review_stats.py --json
    python3 scripts/gate_review_stats.py claude_primary_2026-07-23_unified_diff
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.harness.models import HarnessStage  # noqa: E402  (needs sys.path above)

# Imported, never re-listed: the trust vocabulary has to be the harness's own or
# the review can silently disagree with the runner about what counts as a pass.
from src.harness.runner import (  # noqa: E402
    PLACEMENT_VERIFIED_MODES,
    QUARANTINED_MODES,
)

HARNESS_RESULTS = REPO_ROOT / "harness_results"
CANDIDATE_ARTIFACTS = REPO_ROOT / "candidate_artifacts"
EXPERIMENT_LOGS = REPO_ROOT / "experiment_logs"

# The legs the current gate review (v2, 2026-07-30) is computed from.
DEFAULT_RUNS = (
    "claude_primary_2026-07-30_reeval",
    "qwen_robustness_2026-07-30_reeval",
)

REQUIRED_ARTIFACTS = (
    "diff.patch",
    "harness_output.json",
    "metadata.json",
    "prompt.txt",
    "response.txt",
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open() as fh:
        return [json.loads(line) for line in fh if line.strip()]


def load_results(run: str) -> list[dict[str, Any]]:
    return read_jsonl(HARNESS_RESULTS / run / "results.jsonl")


def check_no_duplicate_rows(run: str, rows: list[dict[str, Any]]) -> list[str]:
    """results.jsonl opens in append mode; a re-run into an existing directory
    silently doubles every stage count. Catch that before trusting anything.

    `_check_run_id_available()` now refuses such a re-run up front, but this
    guard stays: it also covers directories written before that guard existed."""
    counts = Counter(r["candidate_id"] for r in rows)
    return [
        f"{run}: candidate_id {cid!r} appears {n}x"
        for cid, n in sorted(counts.items())
        if n > 1
    ]


def stage_matrix(rows: list[dict[str, Any]]) -> dict[tuple[str, str], Counter]:
    matrix: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for r in rows:
        matrix[(r["task_id"], r["condition"])][(r["stage"], r["apply_mode"])] += 1
    return matrix


def is_verified_pass(row: dict[str, Any]) -> bool:
    """A pass we are willing to count: reached test_pass AND its edit landed at a
    placement the harness verified."""
    return (
        row["stage"] == HarnessStage.test_pass.value
        and row.get("apply_mode") in PLACEMENT_VERIFIED_MODES
    )


def is_quarantined(row: dict[str, Any]) -> bool:
    return row.get("apply_mode") in QUARANTINED_MODES


def conditions_in(rows: list[dict[str, Any]]) -> list[str]:
    """Conditions are read off the data, not hardcoded — `whole_file` joined the
    default set after the first version of this script was written."""
    return sorted({r["condition"] for r in rows})


def condition_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-condition arithmetic over the whole task set.

    No task is excluded. The old script excluded P1, whose KG-augmented arm was
    expected-fail by construction while `Custom_Hook` nodes were missing from the
    KG; that extraction defect is fixed and P1's KG arm now retrieves rows, so
    the exclusion would understate the leg rather than protect it."""
    out: dict[str, Any] = {}
    for condition in conditions_in(rows):
        subset = [r for r in rows if r["condition"] == condition]
        out[condition] = {
            "n": len(subset),
            "verified_pass": sum(1 for r in subset if is_verified_pass(r)),
            "quarantined": sum(1 for r in subset if is_quarantined(r)),
            "applied_at_all": sum(1 for r in subset if r.get("apply_mode") is not None),
            "per_task": {
                task: {
                    "n": sum(1 for r in subset if r["task_id"] == task),
                    "verified_pass": sum(
                        1 for r in subset if r["task_id"] == task and is_verified_pass(r)
                    ),
                }
                for task in sorted({r["task_id"] for r in subset})
            },
        }
    return out


def distinct_diffs(run: str, rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, int]]:
    """Are the n=5 replicates the same patch repeated, or genuinely distinct
    patches that converged on one outcome? The gate reading depends on this."""
    buckets: dict[tuple[str, str], list[str]] = defaultdict(list)
    for r in rows:
        patch = CANDIDATE_ARTIFACTS / run / r["candidate_id"] / "diff.patch"
        if patch.exists():
            buckets[(r["task_id"], r["condition"])].append(
                hashlib.sha256(patch.read_bytes()).hexdigest()
            )
    return {
        key: {"replicates": len(hashes), "distinct": len(set(hashes))}
        for key, hashes in sorted(buckets.items())
    }


def artifact_completeness(run: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    missing: list[str] = []
    empty: list[str] = []
    for r in rows:
        cand_dir = CANDIDATE_ARTIFACTS / run / r["candidate_id"]
        for name in REQUIRED_ARTIFACTS:
            f = cand_dir / name
            if not f.exists():
                missing.append(f"{r['candidate_id']}/{name}")
            elif f.stat().st_size == 0:
                empty.append(f"{r['candidate_id']}/{name}")
    return {
        "candidates": len(rows),
        "files_expected": len(rows) * len(REQUIRED_ARTIFACTS),
        "missing": missing,
        "empty": empty,
        "complete": not missing and not empty,
    }


def output_formats(run: str, rows: list[dict[str, Any]]) -> dict[str, int]:
    """How the generator was asked to express its edit. Run-level by design, so
    anything but a single value across a leg means two variables moved at once."""
    seen: Counter = Counter()
    for r in rows:
        meta_path = CANDIDATE_ARTIFACTS / run / r["candidate_id"] / "metadata.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            seen[str(meta.get("output_format"))] += 1
    return dict(seen)


def retrieval_tokens(run: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    per_cell: dict[tuple[str, str], list[int]] = defaultdict(list)
    generator_usage: dict[tuple[str, str], list[dict[str, int]]] = defaultdict(list)
    for r in rows:
        meta_path = CANDIDATE_ARTIFACTS / run / r["candidate_id"] / "metadata.json"
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text())
        per_cell[(r["task_id"], r["condition"])].append(meta.get("retrieval_token_count", -1))
        if meta.get("generator_usage"):
            generator_usage[(r["task_id"], r["condition"])].append(meta["generator_usage"])

    cells = {}
    for key, vals in sorted(per_cell.items()):
        usages = generator_usage.get(key, [])
        cells[key] = {
            "retrieval_tokens": sorted(set(vals)),
            "mean_generator_input": (
                round(sum(u["input_tokens"] for u in usages) / len(usages)) if usages else None
            ),
            "mean_generator_output": (
                round(sum(u["output_tokens"] for u in usages) / len(usages)) if usages else None
            ),
        }

    floor_nonzero = {
        key: v["retrieval_tokens"]
        for key, v in cells.items()
        if key[1] == "floor" and any(t != 0 for t in v["retrieval_tokens"])
    }
    return {"cells": cells, "floor_nonzero_violations": floor_nonzero}


def call_decomposition(run: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    log_dir = EXPERIMENT_LOGS / run
    if not log_dir.exists():
        return out
    for log in sorted(log_dir.glob("*.jsonl")):
        records = read_jsonl(log)
        by_purpose: dict[str, dict[str, int]] = defaultdict(
            lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0}
        )
        providers: Counter = Counter()
        models: Counter = Counter()
        temperatures: set[float] = set()
        failures: Counter = Counter()
        for rec in records:
            slot = by_purpose[rec.get("call_purpose", "?")]
            slot["calls"] += 1
            usage = rec.get("usage") or {}
            slot["input_tokens"] += usage.get("input_tokens", 0)
            slot["output_tokens"] += usage.get("output_tokens", 0)
            providers[rec.get("openrouter_provider")] += 1
            models[rec.get("model_id")] += 1
            temperatures.add((rec.get("params") or {}).get("temperature"))
            if rec.get("error"):
                failures[str(rec.get("error"))[:120]] += 1
        out[log.stem] = {
            "total_calls": len(records),
            "by_purpose": dict(by_purpose),
            "openrouter_providers": dict(providers),
            "models": dict(models),
            "temperatures": sorted(t for t in temperatures if t is not None),
            "errors": dict(failures),
        }
    return out


def rate_limit_headroom(run: str) -> dict[str, Any]:
    """Observed provider headroom, from the `rate_limit` block every Phase 2 call
    logs since 2026-07-30. `phase2_call_delay` was derived from these numbers, so
    a leg that reports them verifies the derivation instead of assuming it."""
    log_dir = EXPERIMENT_LOGS / run
    if not log_dir.exists():
        return {}
    limits: dict[str, set[str]] = defaultdict(set)
    min_remaining: dict[str, int] = {}
    calls_with_headers = 0
    total = 0
    for log in sorted(log_dir.glob("*.jsonl")):
        for rec in read_jsonl(log):
            total += 1
            rl = rec.get("rate_limit") or {}
            if not rl:
                continue
            calls_with_headers += 1
            for key, value in rl.items():
                if key.endswith("_limit"):
                    limits[key].add(str(value))
                elif key.endswith("_remaining"):
                    try:
                        n = int(value)
                    except (TypeError, ValueError):
                        continue
                    min_remaining[key] = min(min_remaining.get(key, n), n)
    return {
        "calls": total,
        "calls_with_rate_limit_headers": calls_with_headers,
        "limits": {k: sorted(v) for k, v in sorted(limits.items())},
        "min_remaining": dict(sorted(min_remaining.items())),
    }


def classifier_outputs(run: str) -> dict[str, Counter]:
    """What the classifier decided, per distinct response. Determinism across
    replicates is itself a finding."""
    out: dict[str, Counter] = {}
    log = EXPERIMENT_LOGS / run / "kg_augmented.jsonl"
    responses: Counter = Counter()
    for rec in read_jsonl(log):
        if rec.get("call_purpose") == "classifier":
            responses[str(rec.get("response", "")).strip()] += 1
    if responses:
        out["kg_augmented"] = responses
    return out


def apply_tier_split(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The apply ladder is condition-agnostic (docker/entrypoint.sh does not know
    the condition), so this is reported as an observation, never as a difference
    in how the arms were treated.

    `apply_reason` is reported alongside `apply_mode` because `diff_apply_fail`
    on its own conflates unrelated causes — a missing file, a SEARCH block that
    matched nothing, and an ambiguous match are three different findings."""
    tiers = Counter(r.get("apply_mode") for r in rows)
    reasons = Counter(r.get("apply_reason") for r in rows if r.get("apply_reason"))
    return {
        "by_apply_mode": {str(k): v for k, v in sorted(tiers.items(), key=lambda kv: str(kv[0]))},
        "by_apply_reason": {str(k): v for k, v in sorted(reasons.items())},
        "verified_placement": sum(
            1 for r in rows if r.get("apply_mode") in PLACEMENT_VERIFIED_MODES
        ),
        "quarantined": sum(1 for r in rows if is_quarantined(r)),
        "never_applied": sum(1 for r in rows if r.get("apply_mode") is None),
        "candidates": len(rows),
    }


def reference_patch_timings() -> dict[str, Any]:
    rows = read_jsonl(HARNESS_RESULTS / "calibration" / "results.jsonl")
    per_task: dict[str, list[float]] = defaultdict(list)
    stages: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        per_task[r["task_id"]].append(r.get("duration_ms", 0.0))
        stages[r["task_id"]].add(r["stage"])
    return {
        task: {
            "runs": len(durations),
            "max_seconds": round(max(durations) / 1000.0, 1),
            "stages": sorted(stages[task]),
            "under_60s": max(durations) / 1000.0 < 60.0,
        }
        for task, durations in sorted(per_task.items())
    }


def harness_errors(rows: list[dict[str, Any]]) -> int:
    return sum(1 for r in rows if r["stage"] == HarnessStage.harness_error.value)


def build_run_report(run: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Every block is computed for every leg. The old script computed diffs,
    retrieval tokens and classifier outputs for the primary leg only, which is
    why the open-model leg could never be assessed on the same footing."""
    retrieval = retrieval_tokens(run, rows)
    return {
        "candidates": len(rows),
        "tasks": sorted({r["task_id"] for r in rows}),
        "conditions": conditions_in(rows),
        "output_formats": output_formats(run, rows),
        "stage_matrix": {
            f"{t}/{c}": {f"{s}/{am}": n for (s, am), n in sorted(counter.items())}
            for (t, c), counter in sorted(stage_matrix(rows).items())
        },
        "harness_errors": harness_errors(rows),
        "apply_tiers": apply_tier_split(rows),
        "distinct_diffs": {
            f"{t}/{c}": v for (t, c), v in distinct_diffs(run, rows).items()
        },
        "artifacts": artifact_completeness(run, rows),
        "retrieval": {
            "cells": {f"{t}/{c}": v for (t, c), v in retrieval["cells"].items()},
            "floor_nonzero_violations": {
                f"{t}/{c}": v for (t, c), v in retrieval["floor_nonzero_violations"].items()
            },
        },
        "calls": call_decomposition(run),
        "rate_limit": rate_limit_headroom(run),
        "classifier_outputs": {k: dict(v) for k, v in classifier_outputs(run).items()},
        "condition_summary": condition_summary(rows),
    }


def build_report(runs: tuple[str, ...]) -> dict[str, Any]:
    loaded = {run: load_results(run) for run in runs}

    integrity: list[str] = []
    for run, rows in loaded.items():
        if not rows:
            integrity.append(f"{run}: no results.jsonl rows found under harness_results/")
        integrity.extend(check_no_duplicate_rows(run, rows))

    return {
        "runs_requested": list(runs),
        "integrity_warnings": integrity,
        "trust_vocabulary": {
            "placement_verified": sorted(PLACEMENT_VERIFIED_MODES),
            "quarantined": sorted(QUARANTINED_MODES),
        },
        "runs": {run: build_run_report(run, rows) for run, rows in loaded.items()},
        "reference_patch_timings": reference_patch_timings(),
    }


def emit_human(report: dict[str, Any]) -> None:
    def hdr(text: str) -> None:
        print(f"\n{'=' * 72}\n{text}\n{'=' * 72}")

    if report["integrity_warnings"]:
        hdr("INTEGRITY WARNINGS")
        for w in report["integrity_warnings"]:
            print(f"  !! {w}")
    else:
        hdr("INTEGRITY")
        print("  OK — every requested leg has rows, no duplicate candidate_id.")

    tv = report["trust_vocabulary"]
    print(f"\n  placement-verified apply modes: {tv['placement_verified']}")
    print(f"  quarantined apply modes:        {tv['quarantined']}")

    for run, data in report["runs"].items():
        hdr(f"RUN: {run}  ({data['candidates']} candidates)")
        print(f"  tasks: {data['tasks']}   conditions: {data['conditions']}")
        print(f"  output_format: {data['output_formats'] or 'n/a'}")
        print(f"  harness_errors: {data['harness_errors']}")
        print("\n  stage x (task/condition):")
        for cell, counts in data["stage_matrix"].items():
            print(f"    {cell:<26} {counts}")
        at = data["apply_tiers"]
        print(f"\n  apply modes:   {at['by_apply_mode']}")
        print(f"  apply reasons: {at['by_apply_reason'] or 'none'}")
        print(
            f"    verified={at['verified_placement']}  quarantined={at['quarantined']}"
            f"  never_applied={at['never_applied']}  / {at['candidates']}"
        )
        arts = data["artifacts"]
        print(
            f"\n  artifacts: {arts['files_expected']} expected, "
            f"missing={len(arts['missing'])}, empty={len(arts['empty'])}, "
            f"complete={arts['complete']}"
        )
        if arts["missing"]:
            print(f"    missing: {arts['missing'][:10]}")
        if arts["empty"]:
            print(f"    empty:   {arts['empty'][:10]}")
        print("\n  distinct diffs per cell:")
        for cell, v in data["distinct_diffs"].items():
            print(f"    {cell:<26} {v['distinct']} distinct of {v['replicates']}")
        print("\n  retrieval tokens / generator usage:")
        for cell, v in data["retrieval"]["cells"].items():
            print(
                f"    {cell:<26} retrieval={v['retrieval_tokens']}"
                f"  gen_in~{v['mean_generator_input']}  gen_out~{v['mean_generator_output']}"
            )
        viol = data["retrieval"]["floor_nonzero_violations"]
        print(f"    floor nonzero-context violations: {viol or 'none'}")
        print("\n  LLM calls:")
        for log_name, v in data["calls"].items():
            print(f"    [{log_name}] total={v['total_calls']}  temps={v['temperatures']}")
            for purpose, s in sorted(v["by_purpose"].items()):
                print(
                    f"       {purpose:<12} calls={s['calls']:<4}"
                    f" in={s['input_tokens']:<8} out={s['output_tokens']}"
                )
            print(f"       models={v['models']}")
            print(f"       openrouter_providers={v['openrouter_providers']}")
            if v["errors"]:
                print(f"       errors={v['errors']}")
        rl = data["rate_limit"]
        if rl:
            print(
                f"\n  rate-limit headers on {rl['calls_with_rate_limit_headers']}"
                f"/{rl['calls']} calls"
            )
            for k, v in rl["limits"].items():
                print(f"       {k:<34} {v}")
            for k, v in rl["min_remaining"].items():
                print(f"       min {k:<30} {v}")
        if data.get("classifier_outputs"):
            print("\n  classifier outputs (response -> count):")
            for _, responses in data["classifier_outputs"].items():
                for resp, n in sorted(responses.items()):
                    print(f"    {n}x  {resp}")
        print("\n  per-condition summary (all tasks, no exclusions):")
        for cond, s in data["condition_summary"].items():
            per_task = "  ".join(
                f"{t}={v['verified_pass']}/{v['n']}" for t, v in s["per_task"].items()
            )
            print(
                f"    {cond:<14} verified={s['verified_pass']}/{s['n']}"
                f"  quarantined={s['quarantined']}  applied={s['applied_at_all']}   {per_task}"
            )

    hdr("REFERENCE PATCH TIMINGS (<60s bar)")
    for task, v in report["reference_patch_timings"].items():
        print(
            f"  {task}: {v['runs']} runs, max {v['max_seconds']}s, "
            f"stages={v['stages']}, under_60s={v['under_60s']}"
        )
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "runs",
        nargs="*",
        default=list(DEFAULT_RUNS),
        help=f"Run directory names under harness_results/. Default: {' '.join(DEFAULT_RUNS)}",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args()

    report = build_report(tuple(args.runs))
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        emit_human(report)
    return 1 if report["integrity_warnings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
