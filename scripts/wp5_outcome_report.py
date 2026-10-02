"""WP5 outcome report: condition x model x task on the graded scale (IJCKG WP5 acceptance).

Assembles the WP5 cells from the three run pairs that hold them, one run per cell:

    P1-P3  floor, whole_file, kg_augmented   *_2026-09-18_wp5_p1p3
    P1-P3  bm25, text_emb_3_large            *_2026-09-19_wp5_p1p3_baselines
    P4-P6  all five conditions               *_2026-09-19_wp5_p4p6

and reports, per the revision plan's WP5 acceptance:
  - each candidate on the graded scale (never applied / applied but failed to build /
    built but failed the test / passed with a verified placement), with harness errors
    and quarantined candidates in their own columns (src/evaluation/outcomes.py);
  - apply_reason next to the never-applied counts;
  - distinct outputs per cell (temperature 0: variance is provider-side, not sampling);
  - context tokens per cell (the whole-file oracle is uncapped; the others cap at 7000).

Fails if any cell is missing, duplicated across runs, or not n=5.
Writes docs/phase_2/ijckg-2026/wp5_outcomes.{md,csv}.
Run: uv run python scripts/wp5_outcome_report.py
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.evaluation.outcomes import EXCLUDED, OUTCOMES, SCALE, grade, patch_hash  # noqa: E402

RESULTS = Path("harness_results")
ARTIFACTS = Path("candidate_artifacts")
OUT = Path("docs/phase_2/ijckg-2026/wp5_outcomes")

LEGS = {"claude_primary": "Claude Sonnet 4.6", "qwen_robustness": "Qwen3-Coder"}
TASKS = ["P1", "P2", "P3", "P4", "P5", "P6"]
CONDITIONS = ["floor", "whole_file", "kg_augmented", "bm25", "text_emb_3_large"]
COND_LABEL = {
    "floor": "floor", "whole_file": "whole-file (oracle, uncapped)", "kg_augmented": "KG-augmented",
    "bm25": "BM25", "text_emb_3_large": "dense",
}
N = 5
# (run suffix, tasks, conditions) — which run holds which cells.
SOURCES = [
    ("2026-09-18_wp5_p1p3", ["P1", "P2", "P3"], ["floor", "whole_file", "kg_augmented"]),
    ("2026-09-19_wp5_p1p3_baselines", ["P1", "P2", "P3"], ["bm25", "text_emb_3_large"]),
    ("2026-09-19_wp5_p4p6", ["P4", "P5", "P6"], CONDITIONS),
]
LABEL = {"passed": "passed", "test_fail": "test fail", "build_fail": "build fail",
         "never_applied": "never applied", "quarantined": "quarantined", "harness_error": "harness error"}


def load_rows(run: str) -> list[dict]:
    path = RESULTS / run / "results.jsonl"
    if not path.exists():
        sys.exit(f"missing {path}")
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def main() -> None:
    cells: dict[tuple[str, str, str], list[dict]] = defaultdict(list)   # (leg, cond, task) -> rows
    source_of: dict[tuple[str, str, str], str] = {}
    for leg in LEGS:
        for suffix, tasks, conds in SOURCES:
            run = f"{leg}_{suffix}"
            for row in load_rows(run):
                if row["task_id"] not in tasks or row["condition"] not in conds:
                    sys.exit(f"{run}: unexpected cell {row['task_id']}/{row['condition']}")
                key = (leg, row["condition"], row["task_id"])
                if key in source_of and source_of[key] != run:
                    sys.exit(f"cell {key} appears in {source_of[key]} and {run}")
                source_of[key] = run
                row = dict(row, _run=run)
                cells[key].append(row)

    problems = []
    for leg in LEGS:
        for cond in CONDITIONS:
            for task in TASKS:
                rows = cells.get((leg, cond, task), [])
                ids = [r["candidate_id"] for r in rows]
                if len(rows) != N or len(set(ids)) != N:
                    problems.append(f"{leg}/{cond}/{task}: {len(rows)} rows, {len(set(ids))} distinct ids")
    if problems:
        sys.exit("incomplete WP5 matrix:\n  " + "\n  ".join(problems))

    # Per-candidate facts
    stat: dict[tuple, dict] = {}
    for key, rows in cells.items():
        outcomes = Counter(grade(r) for r in rows)
        reasons = Counter(r.get("apply_reason") or "?" for r in rows if grade(r) == "never_applied")
        hashes, tokens = [], []
        for r in rows:
            art = ARTIFACTS / r["_run"] / r["candidate_id"]
            h = patch_hash(art / "diff.patch")
            if h is None:
                sys.exit(f"missing artifact {art / 'diff.patch'}")
            hashes.append(h)
            meta = json.loads((art / "metadata.json").read_text(encoding="utf-8"))
            tokens.append(meta.get("retrieval_token_count") or 0)
        stat[key] = {"outcomes": outcomes, "reasons": reasons, "distinct": len(set(hashes)),
                     "tokens": tokens, "run": rows[0]["_run"]}

    def pooled(leg, cond, tasks=TASKS):
        total = Counter()
        reasons = Counter()
        tokens = []
        for t in tasks:
            s = stat[(leg, cond, t)]
            total += s["outcomes"]
            reasons += s["reasons"]
            tokens += s["tokens"]
        return total, reasons, tokens

    md = [
        "# WP5 — Outcomes on the graded scale",
        "",
        "> Generated by `scripts/wp5_outcome_report.py` from `harness_results/` and",
        "> `candidate_artifacts/`. Do not edit by hand. Outcome mapping: `src/evaluation/outcomes.py`.",
        "",
        f"{len(LEGS)} models × {len(CONDITIONS)} conditions × {len(TASKS)} tasks × n={N} = "
        f"{len(LEGS) * len(CONDITIONS) * len(TASKS) * N} candidates. Each cell comes from exactly one run:",
        "",
        "| Tasks | Conditions | Runs |",
        "|---|---|---|",
    ]
    for suffix, tasks, conds in SOURCES:
        md.append(f"| {', '.join(tasks)} | {', '.join(COND_LABEL[c].split(' (')[0] for c in conds)} | "
                  + ", ".join(f"`{leg}_{suffix}`" for leg in LEGS) + " |")
    md += [
        "",
        "**Scale:**",
        "- *never applied*: `diff_apply_fail`, `timeout_at_apply`;",
        "- *build fail* (applied, but failed to build): `install_fail`, `build_fail`, `setup_crash`, `timeout_at_install`, `timeout_at_build`;",
        "- *test fail* (built, but failed the test): `test_fail`, `timeout_at_test`;",
        "- *passed*: `test_pass` with a placement-verified `apply_mode`.",
        "",
        "Quarantined candidates (`recount_c0`, `whole_file_elided`) and harness errors are **excluded** "
        "and counted in their own columns, never as passes. There is no human or blind grading: the "
        "grade is the automated Docker harness. At temperature 0 the 5 candidates of a cell are "
        "near-identical by design, so *distinct outputs* shows how much the provider's output varies.",
        "",
        "## Per model and condition (all six tasks)",
        "",
        "| Model | Condition | n | " + " | ".join(LABEL[o] for o in OUTCOMES) +
        " | Never-applied reasons | Context tokens (median) |",
        "|---|---|---|" + "---|" * len(OUTCOMES) + "---|---|",
    ]
    csv_rows = []
    for leg, model in LEGS.items():
        for cond in CONDITIONS:
            total, reasons, tokens = pooled(leg, cond)
            n = sum(total.values())
            reason_txt = ", ".join(f"{r} {c}" for r, c in reasons.most_common()) or "—"
            cells_txt = " | ".join(
                f"**{total[o]}**" if o == "passed" else str(total[o]) for o in OUTCOMES
            )
            md.append(f"| {model} | {COND_LABEL[cond]} | {n} | {cells_txt} | {reason_txt} | "
                      f"{statistics.median(tokens):,.0f} |")

    md += [
        "",
        "## Per task: passed / test fail / build fail / never applied (distinct outputs)",
        "",
        "Each cell is 5 candidates. An `x` suffix counts excluded candidates (quarantined + harness error).",
        "",
        "| Model | Condition | " + " | ".join(TASKS) + " |",
        "|---|---|" + "---|" * len(TASKS),
    ]
    for leg, model in LEGS.items():
        for cond in CONDITIONS:
            parts = []
            for task in TASKS:
                s = stat[(leg, cond, task)]
                o = s["outcomes"]
                txt = "/".join(str(o[k]) for k in SCALE) + f" ({s['distinct']})"
                excl = sum(o[k] for k in EXCLUDED)
                if excl:
                    txt += f" +{excl}x"
                parts.append(txt)
                reasons = s["reasons"]
                csv_rows.append({
                    "model": model, "leg": leg, "condition": cond, "task": task, "run": s["run"], "n": N,
                    **{o_: o[o_] for o_ in OUTCOMES},
                    "never_applied_reasons": ";".join(f"{r}={c}" for r, c in sorted(reasons.items())),
                    "distinct_outputs": s["distinct"],
                    "context_tokens_median": statistics.median(s["tokens"]),
                })
            md.append(f"| {model} | {COND_LABEL[cond]} | " + " | ".join(parts) + " |")

    md += [
        "",
        "## Passed, per task (compact)",
        "",
        "| Model | Condition | " + " | ".join(TASKS) + " | Total |",
        "|---|---|" + "---|" * len(TASKS) + "---|",
    ]
    for leg, model in LEGS.items():
        for cond in CONDITIONS:
            row = [stat[(leg, cond, t)]["outcomes"]["passed"] for t in TASKS]
            md.append(f"| {model} | {COND_LABEL[cond]} | " + " | ".join(map(str, row)) +
                      f" | **{sum(row)}/{N * len(TASKS)}** |")

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
