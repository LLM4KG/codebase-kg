"""WP12 outcome report: the matched ablation beside the published 7,000-token arms.

Two views of the same two retrievers, per model x task on the graded scale:

  published   bm25 / text_emb_3_large at the 7,000-token cap   (the WP5 runs)
  matched     the same two capped at the KG's own per-task context (the WP12 runs)

and, beside them, the KG arm they are matched to — so the table answers the
question the paper needs: is the KG's value what it selects, or only that it is
cheap? Also reports the context actually used, USD per candidate, and the
retrieval-side retention measured by scripts/wp12_matched_retrieval_diag.py.

An ABLATION, not a sixth and seventh baseline: the published view is always
reported beside the matched one, and neither table is quoted without the other.

Does NOT touch scripts/wp5_outcome_report.py, which asserts an exact cell matrix
and exits on an unexpected condition: WP5's artifact must keep regenerating
byte-identically.

Writes docs/phase_2/ijckg-2026/wp12_matched.{md,csv}.
Run: uv run python scripts/wp12_matched_report.py
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.evaluation.cost import CostReport, UnpricedCall, by_generator_model, match_task  # noqa: E402
from src.evaluation.outcomes import EXCLUDED, OUTCOMES, SCALE, grade, patch_hash  # noqa: E402
from src.generation.orchestrator import load_task_spec  # noqa: E402
from src.retrieval.config import load_condition_config  # noqa: E402

RESULTS = Path("harness_results")
ARTIFACTS = Path("candidate_artifacts")
LOGS = Path("experiment_logs")
OUT = Path("docs/phase_2/ijckg-2026/wp12_matched")
RETENTION = Path("docs/phase_2/ijckg-2026/wp12_matched_retrieval.csv")

LEGS = {"claude_primary": "Claude Sonnet 4.6", "qwen_robustness": "Qwen3-Coder"}
GEN_MODEL = {"claude_primary": "anthropic/claude-sonnet-4-6",
             "qwen_robustness": "openrouter/qwen/qwen3-coder"}
TASKS = ["P1", "P2", "P3", "P4", "P5", "P6"]
N = 5

# (condition, view) -> the run suffix holding each task's cells.
# The published arms come from WP5's runs and are NOT re-run; the KG arm is the
# thing they are matched against and is reported unchanged.
SOURCES: dict[tuple[str, str], dict[str, str]] = {
    ("bm25", "published"): {**dict.fromkeys(["P1", "P2", "P3"], "2026-09-19_wp5_p1p3_baselines"),
                            **dict.fromkeys(["P4", "P5", "P6"], "2026-09-19_wp5_p4p6")},
    ("text_emb_3_large", "published"): {**dict.fromkeys(["P1", "P2", "P3"], "2026-09-19_wp5_p1p3_baselines"),
                                        **dict.fromkeys(["P4", "P5", "P6"], "2026-09-19_wp5_p4p6")},
    ("kg_augmented", "published"): {**dict.fromkeys(["P1", "P2", "P3"], "2026-09-18_wp5_p1p3"),
                                    **dict.fromkeys(["P4", "P5", "P6"], "2026-09-19_wp5_p4p6")},
    ("bm25_matched", "matched"): dict.fromkeys(TASKS, "2026-09-21_wp12_matched"),
    ("text_emb_3_large_matched", "matched"): dict.fromkeys(TASKS, "2026-09-21_wp12_matched"),
}
MATCHED_OF = {"bm25": "bm25_matched", "text_emb_3_large": "text_emb_3_large_matched"}
LABEL = {"bm25": "BM25", "text_emb_3_large": "dense", "kg_augmented": "KG-augmented"}
WP12_RUNS = sorted({f"{leg}_{s}" for leg in LEGS
                    for (c, v), m in SOURCES.items() if v == "matched" for s in m.values()})

BUDGETS = load_condition_config("bm25_matched").retriever_params["token_budget_by_task"]


def rows_of(run: str) -> list[dict]:
    path = RESULTS / run / "results.jsonl"
    if not path.exists():
        sys.exit(f"missing {path} — has the run been done? (WP12 step 5)")
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def collect() -> dict[tuple, dict]:
    """(leg, condition, task) -> graded outcomes, distinct outputs, context tokens."""
    by_run: dict[str, list[dict]] = {}
    stat: dict[tuple, dict] = {}
    problems: list[str] = []
    for leg in LEGS:
        for (cond, _view), per_task in SOURCES.items():
            for task in TASKS:
                run = f"{leg}_{per_task[task]}"
                rows = [r for r in by_run.setdefault(run, rows_of(run))
                        if r["condition"] == cond and r["task_id"] == task]
                ids = {r["candidate_id"] for r in rows}
                if len(rows) != N or len(ids) != N:
                    problems.append(f"{leg}/{cond}/{task} in {run}: {len(rows)} rows, {len(ids)} ids")
                    continue
                hashes, tokens = [], []
                for r in rows:
                    art = ARTIFACTS / run / r["candidate_id"]
                    h = patch_hash(art / "diff.patch")
                    if h is None:
                        sys.exit(f"missing artifact {art / 'diff.patch'}")
                    hashes.append(h)
                    meta = json.loads((art / "metadata.json").read_text(encoding="utf-8"))
                    tokens.append(meta.get("retrieval_token_count") or 0)
                    if cond.endswith("_matched") and tokens[-1] > BUDGETS[task]:
                        sys.exit(f"{r['candidate_id']}: {tokens[-1]} tokens over the "
                                 f"{task} matched budget of {BUDGETS[task]}")
                    if cond.endswith("_matched") and tokens[-1] == 0:
                        sys.exit(f"{r['candidate_id']}: empty context — the floor-fallback "
                                 f"signature. A matched arm must never render nothing.")
                stat[(leg, cond, task)] = {
                    "outcomes": Counter(grade(r) for r in rows),
                    "reasons": Counter(r.get("apply_reason") or "?" for r in rows
                                       if grade(r) == "never_applied"),
                    "distinct": len(set(hashes)),
                    "tokens": tokens,
                    "run": run,
                }
    if problems:
        sys.exit("incomplete WP12 matrix:\n  " + "\n  ".join(problems))
    return stat


def costs() -> dict[tuple, float]:
    """(generator_model, condition, task) -> USD per candidate, for the matched runs."""
    specs = {t: load_task_spec(t) for t in TASKS}
    rep = CostReport()
    for run in WP12_RUNS:
        d = LOGS / run
        if not d.is_dir():
            sys.exit(f"missing {d}")
        for f in sorted(d.glob("*.jsonl")):
            for line in f.open(encoding="utf-8"):
                if not line.strip():
                    continue
                rec = json.loads(line)
                try:
                    rep.add(run, rec, match_task(rec, specs))
                except UnpricedCall as exc:
                    sys.exit(f"{run}: {exc}")
    agg, cands = by_generator_model(rep, list(GEN_MODEL.values()))
    return {k: sum(t.usd for t in agg[k].values()) / cands[k] for k in agg if cands.get(k)}


def retention() -> dict[tuple[str, str], dict]:
    if not RETENTION.exists():
        sys.exit(f"missing {RETENTION} — run scripts/wp12_matched_retrieval_diag.py first")
    out = {}
    with RETENTION.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out[(r["task"], r["retriever"], r["budget_label"])] = r
    return out


def cell(s: dict) -> str:
    txt = "/".join(str(s["outcomes"][k]) for k in SCALE) + f" ({s['distinct']})"
    excl = sum(s["outcomes"][k] for k in EXCLUDED)
    return txt + (f" +{excl}x" if excl else "")


def main() -> None:
    stat = collect()
    usd = costs()
    ret = retention()

    def passed(leg, cond):
        return [stat[(leg, cond, t)]["outcomes"]["passed"] for t in TASKS]

    md = [
        "# WP12 — Context-budget-matched ablation",
        "",
        "> Generated by `scripts/wp12_matched_report.py` from `harness_results/`,",
        "> `candidate_artifacts/` and `experiment_logs/`. Do not edit by hand.",
        "> Outcome mapping: `src/evaluation/outcomes.py`. Prices: `src/evaluation/cost.py`.",
        "",
        "## What this is, and what it is not",
        "",
        "The WP5 comparison is confounded by context length: the KG-augmented arm retrieves",
        "371–1,532 tokens per task while BM25 and dense fill to 4,602–6,981, so "
        "\"BM25 30/30 vs KG 25/30\"",
        "compares retrieval quality **and** budget at once. This ablation re-runs the two",
        "baselines capped at exactly the KG's own measured per-task context — P1 "
        + ", ".join(f"{t} {BUDGETS[t]:,}" for t in TASKS).replace("P1 ", "", 1) + " tokens —",
        "and reports both views.",
        "",
        "It is an **ablation, not a sixth and seventh baseline**: nobody deploys BM25 at 371",
        "tokens, and the published 7,000-token view below is the realistic-deployment",
        "comparison. Neither table should be quoted without the other. The KG arm and the",
        "oracle are unchanged and were **not re-run**; the oracle stays uncapped, because",
        "capping it would stop it being an upper bound (ground rule 2).",
        "",
        "## Passed, per task — published cap vs matched budget",
        "",
        "| Model | Retriever | View | " + " | ".join(TASKS) + " | Total |",
        "|---|---|---|" + "---|" * len(TASKS) + "---|",
    ]
    csv_rows = []
    for leg, model in LEGS.items():
        for base in ("bm25", "text_emb_3_large"):
            for cond, view, cap in (
                (base, "published", "7,000"),
                (MATCHED_OF[base], "matched", "KG's own"),
            ):
                row = passed(leg, cond)
                md.append(f"| {model} | {LABEL[base]} | {view} ({cap}) | "
                          + " | ".join(map(str, row)) + f" | **{sum(row)}/{N * len(TASKS)}** |")
        row = passed(leg, "kg_augmented")
        md.append(f"| {model} | KG-augmented | unchanged | " + " | ".join(map(str, row))
                  + f" | **{sum(row)}/{N * len(TASKS)}** |")

    md += [
        "",
        "## The graded scale, per cell",
        "",
        "Each cell is 5 candidates as *passed / test fail / build fail / never applied*, with",
        "distinct outputs in brackets and excluded candidates (quarantined + harness error) as",
        "`+Nx`. Quarantined candidates are never folded into passes.",
        "",
        "| Model | Retriever | View | " + " | ".join(TASKS) + " |",
        "|---|---|---|" + "---|" * len(TASKS),
    ]
    for leg, model in LEGS.items():
        for base in ("bm25", "text_emb_3_large", "kg_augmented"):
            views = [(base, "published")] + (
                [(MATCHED_OF[base], "matched")] if base in MATCHED_OF else []
            )
            for cond, view in views:
                md.append(f"| {model} | {LABEL[base]} | {view} | "
                          + " | ".join(cell(stat[(leg, cond, t)]) for t in TASKS) + " |")

    md += [
        "",
        "## Context actually used, and what it cost",
        "",
        "Median `retrieval_token_count` over the cell's 5 candidates, and USD per candidate.",
        "The published arms' cost is in `wp9_phase2_cost.md`; only the matched runs are new",
        "spend.",
        "",
        "| Model | Retriever | View | " + " | ".join(TASKS) + " | USD / candidate |",
        "|---|---|---|" + "---|" * len(TASKS) + "---|",
    ]
    for leg, model in LEGS.items():
        for base in ("bm25", "text_emb_3_large", "kg_augmented"):
            views = [(base, "published")] + (
                [(MATCHED_OF[base], "matched")] if base in MATCHED_OF else []
            )
            for cond, view in views:
                toks = " | ".join(
                    f"{statistics.median(stat[(leg, cond, t)]['tokens']):,.0f}" for t in TASKS
                )
                u = usd.get((GEN_MODEL[leg], cond, None))
                md.append(f"| {model} | {LABEL[base]} | {view} | {toks} | "
                          + (f"{u:.4f}" if u is not None else "— (WP5, see wp9_phase2_cost.md)")
                          + " |")

    md += [
        "",
        "## Why the matched arms move: retrieval-side retention",
        "",
        "From `wp12_matched_retrieval.md` — whether the file the reference patch edits is",
        "still in the context at the matched budget. A generation result only moves when the",
        "target file moved.",
        "",
        "| Task | Budget | Files to edit | BM25 published | BM25 matched | dense published | dense matched |",
        "|---|---|---|---|---|---|---|",
    ]
    for task in TASKS:
        base_row = ret[(task, "bm25", "7000")]
        n = int(base_row["target_files_modified"])
        cells = []
        for which in ("bm25", "dense"):
            for label in ("7000", "matched"):
                k = int(ret[(task, which, label)]["target_files_retained"])
                c = f"{k}/{n}"
                cells.append(f"**{c}**" if k < n else c)
        md.append(f"| {task} | {BUDGETS[task]:,} | {n} | " + " | ".join(cells) + " |")

    for leg, model in LEGS.items():
        for base in ("bm25", "text_emb_3_large", "kg_augmented"):
            for cond, view in ([(base, "published")]
                               + ([(MATCHED_OF[base], "matched")] if base in MATCHED_OF else [])):
                for task in TASKS:
                    s = stat[(leg, cond, task)]
                    csv_rows.append({
                        "model": model, "leg": leg, "retriever": base, "view": view,
                        "condition": cond, "task": task, "run": s["run"], "n": N,
                        "token_budget": BUDGETS[task] if view == "matched" else 7000,
                        **{o: s["outcomes"][o] for o in OUTCOMES},
                        "never_applied_reasons": ";".join(
                            f"{r}={c}" for r, c in sorted(s["reasons"].items())
                        ),
                        "distinct_outputs": s["distinct"],
                        "context_tokens_median": statistics.median(s["tokens"]),
                        "usd_per_candidate": (
                            f"{usd[(GEN_MODEL[leg], cond, task)]:.6f}"
                            if (GEN_MODEL[leg], cond, task) in usd else ""
                        ),
                    })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.with_suffix(".md").write_text("\n".join(md) + "\n", encoding="utf-8")
    with OUT.with_suffix(".csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(csv_rows[0]))
        w.writeheader()
        w.writerows(csv_rows)
    print("\n".join(md))
    print(f"\nwrote {OUT.with_suffix('.md')} and {OUT.with_suffix('.csv')} ({len(csv_rows)} rows)")


if __name__ == "__main__":
    main()
