"""Retrieval-side evidence for the context-budget-matched ablation (IJCKG WP12 step 1).

No generation, no Docker, no API spend: BM25 and dense are run over each task's repo
twice — at the published 7,000-token cap and at that task's matched budget (the KG
arm's own measured context) — and what each one selected is compared. It answers the
confound question on its own: if the generation runs slip, this table still shows
whether the baselines' advantage was selection or budget.

Budgets are read from conditions/base/*_matched.toml, so this script and the runs
cannot disagree about what "matched" means. Task statements come through the
orchestrator's own loader, so the query text is byte-identical to the runs'.

Dense reads the committed embedding_cache/ and asserts `api_calls == 0` on every
call: a cache miss here would be a silent bill and a number that is not reproducible.

Writes docs/phase_2/ijckg-2026/wp12_matched_retrieval.{md,csv}.
Run: uv run python scripts/wp12_matched_retrieval_diag.py
"""

from __future__ import annotations

import asyncio
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import get_settings  # noqa: E402
from src.generation.orchestrator import (  # noqa: E402
    _load_task_yaml,
    load_task_spec,
    resolve_repo_root,
)
from src.retrieval.assembler import DEFAULT_TOKEN_BUDGET  # noqa: E402
from src.retrieval.bm25_retriever import BM25Retriever  # noqa: E402
from src.retrieval.config import load_condition_config  # noqa: E402
from src.retrieval.dense_retriever import DenseRetriever  # noqa: E402

TASKS = ["P1", "P2", "P3", "P4", "P5", "P6"]
OUT = Path("docs/phase_2/ijckg-2026/wp12_matched_retrieval")
RUN_ID = "wp12_matched_retrieval_diag"

BM25_CFG = load_condition_config("bm25")
DENSE_CFG = load_condition_config("text_emb_3_large")
BUDGETS = load_condition_config("bm25_matched").retriever_params["token_budget_by_task"]

# Sanity: the two matched TOMLs are generated from one table, so they must agree.
assert (
    load_condition_config("text_emb_3_large_matched").retriever_params["token_budget_by_task"]
    == BUDGETS
), "the two *_matched TOMLs disagree — re-run scripts/wp12_make_matched_conditions.py"


async def retrieve(which: str, task: str, budget: int):
    y = _load_task_yaml(task)
    project = y["project_id"]
    excl = get_settings().projects[project].exclude_paths
    root = resolve_repo_root(project)
    spec = load_task_spec(task)
    common = dict(
        task_type=y.get("task_type", ""), project_name=project,
        exclude_paths=excl, token_budget=budget,
    )
    if which == "bm25":
        r = BM25Retriever(BM25_CFG, **common)
    else:
        r = DenseRetriever(DENSE_CFG, run_id=RUN_ID, **common)
    result = await r.retrieve(spec, "", root)
    if which == "dense" and result.metadata["api_calls"] != 0:
        sys.exit(
            f"{task}/{which} @{budget}: {result.metadata['api_calls']} embedding API call(s) — "
            f"this script must be a cache-only read. Check embedding_cache/ is committed and "
            f"that the task statement has not changed."
        )
    return result


def rank_of(metadata: dict, path: str) -> str:
    top = [x["path"] for x in metadata["ranked_top"]]
    return str(top.index(path) + 1) if path in top else f">{len(top)}"


async def main() -> None:
    rows: list[dict] = []
    for task in TASKS:
        y = _load_task_yaml(task)
        budget = BUDGETS[task]
        # `files_created` are unretrievable by construction — nothing on disk to rank
        # — so they are reported and excluded from the retention counts rather than
        # scored as misses. P3's useCopyToClipboard.ts is the only one.
        modified = list(y.get("files_modified") or [])
        created = list(y.get("files_created") or [])
        for which in ("bm25", "dense"):
            for label, b in (("7000", DEFAULT_TOKEN_BUDGET), ("matched", budget)):
                r = await retrieve(which, task, b)
                md = r.metadata
                kept = [f for f in modified if f in md["included_files"]]
                rows.append({
                    "task": task,
                    "project": y["project_id"],
                    "retriever": which,
                    "budget_label": label,
                    "token_budget": b,
                    "corpus_size": md["corpus_size"],
                    "files_included": len(md["included_files"]),
                    "context_tokens": r.total_token_count,
                    "target_files_modified": len(modified),
                    "target_files_retained": len(kept),
                    "target_files_dropped": ";".join(f for f in modified if f not in kept),
                    "target_ranks": ";".join(f"{Path(f).name}={rank_of(md, f)}" for f in modified),
                    "files_created_unretrievable": ";".join(created),
                    "included_files": ";".join(md["included_files"]),
                })
                print(f"  {task} {which:5s} @{label:7s} "
                      f"{r.total_token_count:>5,} tok, {len(md['included_files']):>2} files, "
                      f"targets {len(kept)}/{len(modified)}")

    by = {(r["task"], r["retriever"], r["budget_label"]): r for r in rows}

    md_lines = [
        "# WP12 — Retrieval-side evidence for the context-budget-matched ablation",
        "",
        "> Generated by `scripts/wp12_matched_retrieval_diag.py`. Do not edit by hand.",
        "> No generation, no Docker, no API spend — dense is a cache-only read and the script",
        "> exits if any embedding call is made. Budgets come from",
        "> `conditions/base/*_matched.toml`, which are themselves generated from",
        "> `wp5_outcomes.csv`, so this table and the runs cannot disagree.",
        "",
        "**What the matched budget is.** Each task's cap is the context the published",
        "`kg_augmented` arm actually retrieved for it — P1 626, P2 1,532, P3 772, P4 371,",
        "P5 497, P6 841 tokens. An **ablation**, not a sixth baseline: nobody deploys BM25 at",
        "371 tokens. It exists to separate *what a retriever selects* from *how much it is",
        "allowed to spend*, which the 7,000-token comparison conflates.",
        "",
        "## Context actually used, and how much of it is the same files",
        "",
        "| Task | Budget | BM25 tokens / files | dense tokens / files | corpus |",
        "|---|---|---|---|---|",
    ]
    for task in TASKS:
        for label in ("7000", "matched"):
            b = by[(task, "bm25", label)]
            d = by[(task, "dense", label)]
            cap = f"{b['token_budget']:,}"
            md_lines.append(
                f"| {task if label == '7000' else ''} | "
                f"{'published cap' if label == '7000' else 'matched'} ({cap}) | "
                f"{b['context_tokens']:,} / {b['files_included']} | "
                f"{d['context_tokens']:,} / {d['files_included']} | "
                f"{b['corpus_size'] if label == '7000' else ''} |"
            )

    md_lines += [
        "",
        "## Target-file retention",
        "",
        "Does the baseline still see the file the reference patch edits? Files the task",
        "*creates* are unretrievable by construction and are excluded from the counts.",
        "",
        "| Task | Files to edit | BM25 @7000 | BM25 @matched | dense @7000 | dense @matched |",
        "|---|---|---|---|---|---|",
    ]
    for task in TASKS:
        n = by[(task, "bm25", "7000")]["target_files_modified"]
        cells = []
        for which in ("bm25", "dense"):
            for label in ("7000", "matched"):
                r = by[(task, which, label)]
                k = r["target_files_retained"]
                cell = f"{k}/{n}" if n > 1 else ("✓" if k else "✗")
                cells.append(f"**{cell}**" if k < n else cell)
        md_lines.append(f"| {task} | {n} | " + " | ".join(cells) + " |")

    created = [(t, by[(t, "bm25", "7000")]["files_created_unretrievable"]) for t in TASKS]
    for t, c in created:
        if c:
            md_lines += ["", f"`{c}` is created by {t}, so no retriever can return it at any "
                             f"budget; it is excluded from {t}'s counts above."]

    md_lines += [
        "",
        "## What each budget drops",
        "",
        "Target files present at 7,000 tokens and absent at the matched budget — the",
        "ranking failures the larger cap was hiding.",
        "",
        "| Task | Retriever | Dropped at the matched budget | Its rank |",
        "|---|---|---|---|",
    ]
    any_dropped = False
    for task in TASKS:
        for which in ("bm25", "dense"):
            wide = set(by[(task, which, "7000")]["included_files"].split(";"))
            r = by[(task, which, "matched")]
            dropped = [f for f in r["target_files_dropped"].split(";") if f and f in wide]
            for f in dropped:
                any_dropped = True
                rank = dict(x.split("=") for x in r["target_ranks"].split(";")).get(Path(f).name, "?")
                md_lines.append(f"| {task} | {which} | `{f}` | {rank} |")
    if not any_dropped:
        md_lines.append("| — | — | nothing: every target retained at both budgets | — |")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.with_suffix(".md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    with OUT.with_suffix(".csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"\nwrote {OUT.with_suffix('.md')} and {OUT.with_suffix('.csv')} ({len(rows)} rows)")


if __name__ == "__main__":
    asyncio.run(main())
