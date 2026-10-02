"""WP8: what the KG retriever does when the anchor is misspelled, wrong, absent or invented.

R3 asked how ambiguous or incorrect anchors are handled. `scripts/wp8_anchor_report.py`
measures what the classifier actually produced; this measures what the retriever does with
an anchor that is wrong — the case WP5 never hit, because all 60 of its classifier calls
produced a resolving anchor.

Five anchor sets per task, run under both resolution modes:

  logged        the anchors the WP5 runs logged, unchanged (the control)
  misspelled    one transposition in the first logged anchor
  wrong         a real component of the same project that the task does not touch
  empty         no anchors at all — the latent bug: `WHERE anchor.name IN []` is false
                for every node, so the anchor-scoped templates return zero rows
  bad_route     the logged anchors plus `/notes/trash`, the route Qwen hallucinated on
                two P2 candidates (feature_addition only; the other templates bind
                $anchorRoutes but never read it)

Per cell it records the resolution status of each anchor, the rows the primary template
returned, the rendered context tokens, and `anchor_fallback`. Retrieval only: no
generator call, no harness, no API, no writes to any run directory. The classifier is
replayed, not called (`KGAugmentedRetriever.retrieve_classified`).

The `logged` + `strict` row doubles as the regression guard: its token count must equal
the `context_tokens_median` that wp5_outcomes.csv records for that task.

Point the pipeline at the scratch Memgraph, never the main one:

    PIPELINE_DB__URI=bolt://localhost:7688 uv run python scripts/wp8_anchor_robustness.py

Writes docs/phase_2/ijckg-2026/wp8_anchor_robustness.{md,json}.
"""

from __future__ import annotations

import asyncio
import csv
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import get_settings  # noqa: E402
from src.generation.kg_loader import (  # noqa: E402
    GRAPH_EXPORT_DIR,
    import_cypherl,
    resolve_project_id,
    wipe_database,
)
from src.generation.orchestrator import (  # noqa: E402
    _load_task_yaml,
    _task_project,
    load_task_spec,
    resolve_repo_root,
)
from src.retrieval.classifier import ClassifierResult  # noqa: E402
from src.retrieval.config import load_experiment_config  # noqa: E402
from src.retrieval.kg_retriever import KGAugmentedRetriever  # noqa: E402

DOCS = Path("docs/phase_2/ijckg-2026")
OUT = DOCS / "wp8_anchor_robustness"
WP5 = DOCS / "wp5_outcomes.csv"
MODES = {"strict": "kg_augmented", "hardened": "kg_augmented_hardened"}

# P1-P3 cover all three task types: bug_fix, feature_addition, refactoring.
# `logged` is the modal classification of the WP5 runs (wp8_anchor_measurement.md §2).
# `misspelled` is one transposition of the first logged anchor; `wrong` is a real
# component of the same repo that the task's reference patch does not touch.
SCENARIOS: dict[str, dict] = {
    "P1": {
        "logged": ["useCartProducts"],
        "misspelled": ["useCartPorducts"],
        "wrong": ["Checkbox"],
    },
    "P2": {
        "logged": ["NoteList"],
        "misspelled": ["NoteLsit"],
        "wrong": ["ContextMenu"],
        "bad_route": ["/notes/trash"],   # what Qwen emitted on 2 of 5 P2 candidates
    },
    "P3": {
        "logged": ["NoteMenuBar", "useCopyToClipboard"],
        "misspelled": ["NoteMenuBra", "useCopyToClipboard"],
        "wrong": ["CategoryList"],
    },
}
CASES = ["logged", "misspelled", "wrong", "empty", "bad_route"]


def wp5_tokens() -> dict[str, int]:
    """task -> the KG condition's median context tokens, as WP5 published them."""
    out: dict[str, int] = {}
    for row in csv.DictReader(WP5.open(encoding="utf-8")):
        if row["condition"] == "kg_augmented" and row["context_tokens_median"]:
            out[row["task"]] = int(row["context_tokens_median"])
    return out


async def measure(
    retriever: KGAugmentedRetriever,
    classification: ClassifierResult,
    spec: str,
    project_id: str,
    repo_root: Path,
) -> dict:
    """One retrieval, with the row count of every Cypher template it ran."""
    original = retriever._run_query
    rows_by_query: dict[str, int] = {}

    async def counted(name: str, params: dict) -> list[dict]:
        rows = await original(name, params)
        rows_by_query[name] = len(rows)
        return rows

    retriever._run_query = counted
    try:
        result = await retriever.retrieve_classified(classification, spec, project_id, repo_root)
    finally:
        retriever._run_query = original

    meta = result.metadata
    return {
        "tokens": result.total_token_count,
        "queries": rows_by_query,
        "files": sorted(set(result.rounds[0].retrieved_files)),
        "anchor_fallback": meta.get("anchor_fallback"),
        "dispatched": meta.get("anchor_names_dispatched"),
        "resolutions": [
            {
                "requested": r["requested"],
                "status": r["status"],
                "name": r["name"],
                "score": r["score"],
                "alternatives": r["alternatives"],
            }
            for r in meta.get("anchor_resolutions", [])
        ],
        "routes_unknown": meta.get("anchor_routes_unknown"),
    }


async def main() -> None:
    uri = get_settings().db.uri
    if not uri.endswith(":7688") and os.environ.get("WP8_ALLOW_MAIN_DB") != "1":
        sys.exit(f"refusing to wipe {uri}: run with PIPELINE_DB__URI=bolt://localhost:7688")

    published = wp5_tokens()
    conds = {mode: load_experiment_config("claude_primary", name).condition
             for mode, name in MODES.items()}
    tasks = list(SCENARIOS)
    project_of = {t: _task_project(t) for t in tasks}

    out: dict = {"db_uri": uri, "wp5_published_tokens": published, "cells": []}
    for project in sorted(set(project_of.values())):
        wipe_database()
        import_cypherl(GRAPH_EXPORT_DIR / project / "full_dump.cypherl")
        project_id = resolve_project_id(project)
        repo_root = resolve_repo_root(project)
        for task in tasks:
            if project_of[task] != project:
                continue
            spec = load_task_spec(task)
            task_type = _load_task_yaml(task)["task_type"]
            scen = SCENARIOS[task]
            for case in CASES:
                if case == "empty":
                    names, routes = [], []
                elif case == "bad_route":
                    if "bad_route" not in scen:
                        continue
                    names, routes = scen["logged"], scen["bad_route"]
                else:
                    names, routes = scen[case], []
                classification = ClassifierResult(
                    task_type=task_type, anchor_names=names, anchor_routes=routes
                )
                for mode, cond in conds.items():
                    retriever = KGAugmentedRetriever(
                        cond, model="replay", run_id="wp8_robustness", project_name=project
                    )
                    got = await measure(retriever, classification, spec, project_id, repo_root)
                    out["cells"].append(
                        {"task": task, "project": project, "task_type": task_type,
                         "case": case, "mode": mode, "anchor_names": names,
                         "anchor_routes": routes, **got}
                    )
                    print(f"{task} {case:11s} {mode:8s} tokens={got['tokens']:5d} "
                          f"fallback={got['anchor_fallback']}", flush=True)

    # The regression guard: strict + logged must reproduce the published token count.
    drift = [
        c for c in out["cells"]
        if c["case"] == "logged" and c["mode"] == "strict"
        and published.get(c["task"]) not in (None, c["tokens"])
    ]
    out["strict_regression_ok"] = not drift
    if drift:
        for c in drift:
            print(f"REGRESSION {c['task']}: strict gives {c['tokens']}, "
                  f"WP5 published {published[c['task']]}", file=sys.stderr)

    Path(f"{OUT}.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    write_markdown(out)
    print(f"wrote {OUT}.md and {OUT}.json")
    if drift:
        sys.exit("strict path drifted from the published WP5 context tokens")


def write_markdown(out: dict) -> None:
    primary = {"bug_fix": "bug_fix.cypher", "feature_addition": "feature_addition_a.cypher",
               "refactoring": "refactoring.cypher"}
    L: list[str] = []
    L.append("# WP8 — anchor robustness: misspelled, wrong, absent and invented anchors")
    L.append("")
    L.append("> Generated by `scripts/wp8_anchor_robustness.py`. **Do not edit by hand.**")
    L.append("> Retrieval only — no generator call, no harness, no API. The classifier is")
    L.append("> replayed, never called. Graph of record loaded into the scratch Memgraph.")
    L.append("")
    L.append("`rows` is what the task's primary anchor-scoped template returned; `tokens` is the")
    L.append("rendered Format-A context. **`empty` is the latent bug** — with no anchor the")
    L.append("`WHERE anchor.name IN $anchorNames` predicate is false for every node.")
    L.append("")
    L.append("| Task | Case | Mode | Rows | Tokens | Fallback | Resolution |")
    L.append("|---|---|---|---|---|---|---|")
    for c in out["cells"]:
        rows = c["queries"].get(primary[c["task_type"]], "—")
        if c["mode"] == "strict":
            detail = "n/a (exact match only)"
        elif c["resolutions"]:
            detail = "; ".join(
                f"`{r['requested']}` -> {r['status']}"
                + (f" `{r['name']}`" if r["name"] and r["name"] != r["requested"] else "")
                + (f" ({r['score']})" if r["score"] else "")
                for r in c["resolutions"]
            )
        else:
            detail = "no anchors to resolve"
        if c["routes_unknown"]:
            detail += f"; route(s) not in graph: {', '.join(c['routes_unknown'])}"
        L.append(
            f"| {c['task']} | {c['case']} | {c['mode']} | {rows} | {c['tokens']} | "
            f"{'**yes**' if c['anchor_fallback'] else ('no' if c['mode'] == 'hardened' else '—')} "
            f"| {detail} |"
        )
    L.append("")
    L.append("## Regression guard")
    L.append("")
    L.append("The `logged` + `strict` cells reproduce the context token counts WP5 published")
    L.append("(`wp5_outcomes.csv`, `context_tokens_median` for `kg_augmented`):")
    L.append("")
    L.append("| Task | strict, logged anchors | WP5 published | Match |")
    L.append("|---|---|---|---|")
    for c in out["cells"]:
        if c["case"] != "logged" or c["mode"] != "strict":
            continue
        pub = out["wp5_published_tokens"].get(c["task"])
        L.append(f"| {c['task']} | {c['tokens']} | {pub} | {'yes' if pub == c['tokens'] else '**NO**'} |")
    L.append("")
    Path(f"{OUT}.md").write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
