#!/usr/bin/env python3
"""Recompute the output-format comparison from run artifacts.

Reads **no prose document** — not the decision log, not the implementation note it
is used to write. Same discipline as `scripts/gate_review_stats.py`, and for the
same reason: several documented numbers in this project have turned out to be
incomplete hand-counts.

Reports, per (output format, condition):

  verified passes   — test_pass on a placement-verified tier. The only number
                      that may be quoted as a pass.
  quarantined       — applied on an unverified tier (recount_c0,
                      whole_file_elided). Reported apart, never folded in.
  applied at all    — reached any stage past the apply step.
  apply_reason      — why the ones that never applied did not.
  mean output tokens— the format's real cost, from the generator call logs.

Usage:
    uv run python scripts/format_comparison_stats.py                    # all runs
    uv run python scripts/format_comparison_stats.py --prefix fmtB_     # one sweep
    uv run python scripts/format_comparison_stats.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.harness.runner import QUARANTINED_MODES, is_placement_verified  # noqa: E402

RESULTS_ROOT = REPO_ROOT / "harness_results"
LOGS_ROOT = REPO_ROOT / "experiment_logs"
ARTIFACTS_ROOT = REPO_ROOT / "candidate_artifacts"


def _load_results(run_dir: Path) -> list[dict]:
    """Per-candidate JSON, not results.jsonl.

    `results.jsonl` opens in append mode (src/harness/results.py), so a re-run into
    an existing directory silently doubles every count. The per-candidate files are
    keyed by candidate_id and overwrite instead.
    """
    return [json.loads(p.read_text()) for p in sorted(run_dir.glob("*.json"))]


def _output_format(run_dir: Path, results: list[dict]) -> str:
    """The format a run used, read from a candidate's metadata.json."""
    for r in results:
        meta = ARTIFACTS_ROOT / run_dir.name / r["candidate_id"] / "metadata.json"
        if meta.exists():
            fmt = json.loads(meta.read_text()).get("output_format")
            if fmt:
                return fmt
    return "unified_diff"      # runs predating the axis


def _generator_tokens(run_name: str) -> dict[str, tuple[int, float, float]]:
    """(n, mean input, mean output) per condition, from the LLM call log."""
    agg: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    log_dir = LOGS_ROOT / run_name
    if not log_dir.exists():
        return {}
    for path in log_dir.glob("*.jsonl"):
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("call_purpose") != "generator":
                continue
            usage = rec.get("usage") or {}
            slot = agg[rec.get("condition_id", "?")]
            slot[0] += 1
            slot[1] += usage.get("input_tokens") or 0
            slot[2] += usage.get("output_tokens") or 0
    return {
        cond: (n, i / n, o / n) for cond, (n, i, o) in agg.items() if n
    }


def analyse(run_dir: Path) -> dict:
    results = _load_results(run_dir)
    if not results:
        return {}

    ids = [r["candidate_id"] for r in results]
    duplicates = [cid for cid, c in Counter(ids).items() if c > 1]

    by_condition: dict[str, dict] = {}
    for r in results:
        cond = by_condition.setdefault(
            r["condition"],
            {
                "n": 0,
                "verified_passes": 0,
                "quarantined": 0,
                "applied_at_all": 0,
                "stages": Counter(),
                "apply_modes": Counter(),
                "apply_reasons": Counter(),
            },
        )
        mode = r.get("apply_mode")
        cond["n"] += 1
        cond["stages"][r["stage"]] += 1
        cond["apply_modes"][mode or "—"] += 1
        if r.get("apply_reason"):
            cond["apply_reasons"][r["apply_reason"]] += 1
        if mode is not None:
            cond["applied_at_all"] += 1
        if mode in QUARANTINED_MODES:
            cond["quarantined"] += 1
        elif r["stage"] == "test_pass" and is_placement_verified(mode):
            cond["verified_passes"] += 1

    return {
        "run": run_dir.name,
        "output_format": _output_format(run_dir, results),
        "total": len(results),
        "duplicate_candidate_ids": duplicates,
        "conditions": by_condition,
        "tokens": _generator_tokens(run_dir.name),
    }


def _fmt_counter(c: Counter) -> str:
    return ", ".join(f"{k}={v}" for k, v in sorted(c.items())) or "—"


def report(runs: list[dict]) -> None:
    for run in runs:
        print(f"\n=== {run['run']}  [{run['output_format']}]  n={run['total']}")
        if run["duplicate_candidate_ids"]:
            print(f"  !! DUPLICATE candidate ids — counts are doubled: "
                  f"{run['duplicate_candidate_ids']}")
        tokens = run["tokens"]
        header = (
            f"  {'condition':14} {'n':>3} {'verified':>9} {'quar':>5} "
            f"{'applied':>8} {'out_tok':>8}  stages"
        )
        print(header)
        for cond, d in sorted(run["conditions"].items()):
            out_tok = f"{tokens[cond][2]:.0f}" if cond in tokens else "—"
            print(
                f"  {cond:14} {d['n']:>3} {d['verified_passes']:>9} "
                f"{d['quarantined']:>5} {d['applied_at_all']:>8} {out_tok:>8}  "
                f"{_fmt_counter(d['stages'])}"
            )
            print(f"  {'':14} {'':>3} modes: {_fmt_counter(d['apply_modes'])}")
            if d["apply_reasons"]:
                print(f"  {'':14} {'':>3} why not: {_fmt_counter(d['apply_reasons'])}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", default="", help="Only runs whose dir name starts with this.")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    runs = []
    for d in sorted(RESULTS_ROOT.iterdir()):
        if not d.is_dir() or not d.name.startswith(args.prefix):
            continue
        analysis = analyse(d)
        if analysis:
            runs.append(analysis)

    if args.json:
        print(json.dumps(runs, indent=2, default=lambda o: dict(o)))
    else:
        report(runs)


if __name__ == "__main__":
    main()
