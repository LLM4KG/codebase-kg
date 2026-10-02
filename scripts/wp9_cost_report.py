"""WP9: cost accounting and break-even — KG construction cost against per-task savings (reviewer R3).

Inputs, all committed:
  - extraction usage per repo: `provenance.usage` of the five cold, `usage.complete: true`
    extractions (graph_export/ for Todoist and Jira Clone, graph_reruns/ for the three
    graphs extracted before WP0 added usage logging);
  - per-task generation cost: experiment_logs/ of the six WP5 runs (as wp9_phase2_cost.py);
  - context tokens and pass counts: wp5_outcomes.csv (scripts/wp5_outcome_report.py);
  - retrieval time: wp9_retrieval_timing.json (scripts/wp9_retrieval_timing.py);
  - dense index cost: the committed embedding caches (each row keeps its batch's usage).

Writes docs/phase_2/ijckg-2026/wp9_cost.{md,csv}.
Run: uv run python scripts/wp9_cost_report.py
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.evaluation.cost import MODEL_LABEL, PRICES, PRICES_FETCHED, call_cost, match_task  # noqa: E402
from src.generation.orchestrator import _task_project, load_task_spec  # noqa: E402

DOCS = Path("docs/phase_2/ijckg-2026")
OUT = DOCS / "wp9_cost"
LOGS = Path("experiment_logs")
EXTRACTIONS = {  # repo -> manifest of its cold, complete extraction
    "react-shopping-cart": Path("graph_reruns/react-shopping-cart/manifest.json"),
    "takenote": Path("graph_reruns/takenote/manifest.json"),
    "SnapShot": Path("graph_reruns/SnapShot/manifest.json"),
    "todoist": Path("graph_export/todoist/manifest.json"),
    "jira_clone": Path("graph_export/jira_clone/manifest.json"),
}
EXTRACTION_MODEL = "anthropic/claude-sonnet-4-6"
EMBED_MODEL = "text-embedding-3-large"
TASKS = ["P1", "P2", "P3", "P4", "P5", "P6"]
LEGS = {"claude_primary": "anthropic/claude-sonnet-4-6", "qwen_robustness": "openrouter/qwen/qwen3-coder"}
WP5_SUFFIXES = ("2026-09-18_wp5_p1p3", "2026-09-19_wp5_p1p3_baselines", "2026-09-19_wp5_p4p6")
CONDS = ["kg_augmented", "bm25", "text_emb_3_large"]
COND_LABEL = {"kg_augmented": "KG", "bm25": "BM25", "text_emb_3_large": "dense"}
N_PER_CELL = 5


def usd(x: float) -> str:
    if x >= 1:
        return f"${x:.2f}"
    return f"${x:.4f}" if x >= 0.001 else f"${x:.6f}"


def priced(model: str, tin: int, tout: int) -> float:
    return call_cost({"model_id": model, "openrouter_provider": None,
                      "usage": {"input_tokens": tin, "output_tokens": tout}})


def extraction_rows() -> list[dict]:
    rows = []
    for repo, path in EXTRACTIONS.items():
        prov = json.loads(path.read_text(encoding="utf-8"))["provenance"]
        u = prov["usage"]
        if not u["complete"] or u["model"] != EXTRACTION_MODEL:
            sys.exit(f"{path}: not a complete {EXTRACTION_MODEL} extraction")
        pf, xf = u["by_stage"]["per_file"], u["by_stage"]["cross_file"]
        total = priced(u["model"], u["input_tokens"], u["output_tokens"])
        rows.append({
            "repo": repo, "manifest": str(path), "run_id": u["run_id"], "files": prov["file_count"],
            "calls": u["calls_api"], "calls_per_file_stage": pf["calls_api"], "calls_cross_file": xf["calls_api"],
            "input_tokens": u["input_tokens"], "output_tokens": u["output_tokens"],
            "usd_per_file_stage": priced(u["model"], pf["input_tokens"], pf["output_tokens"]),
            "usd_cross_file": priced(u["model"], xf["input_tokens"], xf["output_tokens"]),
            "usd": total, "usd_per_source_file": total / prov["file_count"],
            "wall_clock_s": sum(u["wall_clock_s"].values()),
        })
    return rows


def dense_index() -> dict[str, dict]:
    """Per repo: document-index and query tokens from the committed cache (one row per text)."""
    out = {}
    for path in sorted(Path("embedding_cache").glob(f"*/{EMBED_MODEL}.jsonl")):
        batches: dict[str, tuple[str, int]] = {}
        for line in path.open(encoding="utf-8"):
            row = json.loads(line)
            b = row["batch"]
            batches[b["id"]] = (row["kind"], b["prompt_tokens"])
        doc = sum(t for k, t in batches.values() if k == "doc")
        queries = [t for k, t in batches.values() if k == "query"]
        out[path.parent.name] = {"doc_tokens": doc, "doc_usd": priced(EMBED_MODEL, doc, 0),
                                 "query_tokens_median": statistics.median(queries),
                                 "query_usd_median": priced(EMBED_MODEL, int(statistics.median(queries)), 0)}
    return out


def generation_costs(specs: dict[str, str]):
    """(model, cond, task) -> USD summed over the cell; classifier tokens/USD/latency per task."""
    cell_usd: dict[tuple, float] = defaultdict(float)
    clf: dict[tuple, list[dict]] = defaultdict(list)
    for leg, model in LEGS.items():
        for suffix in WP5_SUFFIXES:
            run = f"{leg}_{suffix}"
            for cond in CONDS:
                path = LOGS / run / f"{cond}.jsonl"
                if not path.exists():
                    continue
                pending = 0.0  # embedding calls log no spec; they belong to the next candidate
                for line in path.open(encoding="utf-8"):
                    rec = json.loads(line)
                    purpose = rec.get("call_purpose")
                    task = match_task(rec, specs)
                    if purpose in ("classifier", "generator") and task is None:
                        sys.exit(f"{run}: {purpose} call matches no task")
                    if task is None:
                        pending += call_cost(rec)
                        continue
                    cell_usd[(model, cond, task)] += call_cost(rec) + pending
                    pending = 0.0
                    if purpose == "classifier":
                        u = rec["usage"]
                        clf[(model, task)].append({"in": u["input_tokens"], "out": u["output_tokens"],
                                                   "usd": call_cost(rec), "latency_ms": rec["latency_ms"]})
    return cell_usd, clf


def load_outcomes() -> dict[tuple, dict]:
    out = {}
    with (DOCS / "wp5_outcomes.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out[(LEGS[r["leg"]], r["condition"], r["task"])] = r
    return out


def main() -> None:
    specs = {t: load_task_spec(t) for t in TASKS}
    project_of = {t: _task_project(t) for t in TASKS}
    ext = extraction_rows()
    ext_by_repo = {r["repo"]: r for r in ext}
    dense = dense_index()
    cell_usd, clf = generation_costs(specs)
    outcomes = load_outcomes()
    timing = json.loads((DOCS / "wp9_retrieval_timing.json").read_text(encoding="utf-8"))

    def per_cand(model, cond, task) -> float:
        return cell_usd[(model, cond, task)] / N_PER_CELL

    def cypher_ms(model, task) -> float:
        """Call-weighted median over the classifications the model actually produced."""
        vals = []
        for e in timing["kg"]:
            if e["model"] == model and e["task"] == task:
                vals += [e["cypher_total"]["median_ms"]] * e["calls"]
        return statistics.median(vals)

    md = [
        "# WP9 — Cost accounting and break-even",
        "",
        "> Generated by `scripts/wp9_cost_report.py`. Do not edit by hand. Inputs: extraction manifests, "
        "`experiment_logs/` of the WP5 runs, `wp5_outcomes.csv`, `wp9_retrieval_timing.json`, "
        "`embedding_cache/`. Phase 2 cost per day and provider: `wp9_phase2_cost.md`.",
        "",
        f"Prices (USD per 1M tokens, input / output), dated {PRICES_FETCHED}; provenance in "
        "`src/evaluation/cost.py`:",
        "",
    ]
    for (model, prov), (pin, pout) in PRICES.items():
        md.append(f"- {MODEL_LABEL.get(model, model)}{f' via {prov}' if prov else ''}: {pin:g} / {pout:g}")

    # ---- 1. Extraction ----
    md += [
        "",
        "## 1. KG construction, per repo (one-time)",
        "",
        "Claude Sonnet 4.6, prompt set `72ef9f041851`, cold (no cache, no resume), `usage.complete: true`. "
        "The three graphs built before WP0 added usage logging are costed from their cold re-runs "
        "(`graph_reruns/`, same SHA, file list, prompts and model; WP0 step 7). **No repo is extrapolated.** "
        "Every USD figure matches the Anthropic console (WP1, WP0 step 7).",
        "",
        "| Repo | Source files | LLM calls (per-file / cross-file) | Input tokens | Output tokens | "
        "USD (per-file / cross-file) | USD | USD per file | Wall-clock |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in ext:
        md.append(
            f"| {r['repo']} | {r['files']} | {r['calls']} ({r['calls_per_file_stage']} / {r['calls_cross_file']}) | "
            f"{r['input_tokens']:,} | {r['output_tokens']:,} | "
            f"{usd(r['usd_per_file_stage'])} / {usd(r['usd_cross_file'])} | **{usd(r['usd'])}** | "
            f"{usd(r['usd_per_source_file'])} | {r['wall_clock_s'] / 60:.1f} min |"
        )
    tot = sum(r["usd"] for r in ext)
    md += [
        f"| **all five** | {sum(r['files'] for r in ext)} | {sum(r['calls'] for r in ext):,} | "
        f"{sum(r['input_tokens'] for r in ext):,} | {sum(r['output_tokens'] for r in ext):,} | | **{usd(tot)}** | | "
        f"{sum(r['wall_clock_s'] for r in ext) / 60:.0f} min |",
        "",
        "- 98% of tokens are input: every call resends a few-shot template. Prompt caching would cut "
        "this (future work; not a mid-study change).",
        "- Wall-clock is Stage 2–3 plus Stage 4 at `call_delay = 0`, with the pipeline's concurrency.",
        "- Loading a built KG into Memgraph (import of `full_dump.cypherl`, median of "
        f"{timing['method']['kg_load_reps']}): "
        + ", ".join(f"{p} {v['median_ms'] / 1000:.2f} s" for p, v in timing["kg_load"].items()) + ".",
    ]

    # ---- 2. Baseline indexing ----
    md += [
        "",
        "## 2. Baseline indexing, per repo (one-time)",
        "",
        "| Repo | BM25 index | Dense index: tokens | Dense index: USD | Dense query: tokens (median) | "
        "Dense query: USD |",
        "|---|---|---|---|---|---|",
    ]
    bm25_cold = {p: statistics.median(b["bm25_cold"]["median_ms"] for t, b in timing["baselines"].items()
                                      if b["project"] == p) for p in dense}
    for p, d in dense.items():
        md.append(f"| {p} | $0, {bm25_cold[p]:.0f} ms (read files + build + rank) | {d['doc_tokens']:,} | "
                  f"{usd(d['doc_usd'])} | {d['query_tokens_median']:.0f} | {usd(d['query_usd_median'])} |")
    md += [
        "",
        "- BM25 costs no money: it is local compute. `BM25Retriever` rebuilds its index on every call, "
        "so its index time is also a per-task time (section 3).",
        "- Dense index tokens are the batch usage stored with each committed cache row. In WP5 all but "
        "one query were cache hits (one paid query, attributed to its candidate); the query cost above is "
        "what a new task pays.",
        "- The embedder is the same in both legs (OpenAI), so dense costs the same for Claude and Qwen.",
    ]

    # ---- 3. Per task ----
    md += [
        "",
        "## 3. Per task: retrieval time, context and USD per candidate",
        "",
        "Retrieval time is local and measured by replay (`wp9_retrieval_timing.json`, median of "
        f"{timing['method']['reps']} after {timing['method']['warmup']} warm-up, on "
        f"{timing['host']['machine']} with {timing['host']['cpu_count']} CPUs, Memgraph in Docker on the same "
        "host). KG Cypher time replays each classifier output logged in WP5 through the retriever's "
        "dispatch, against the graph of record; it is Bolt round-trip time for all the task's templates. "
        "The KG's classifier is an LLM call on the generator model, so its latency is shown too. "
        "USD per candidate includes the classifier.",
        "",
        "| Model | Task | Repo | KG classifier: tokens in / out, USD, latency | KG Cypher | "
        "BM25 index + rank | Dense rank (cached) | Context tokens KG / BM25 / dense | "
        "USD per candidate KG / BM25 / dense |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    csv_rows = []
    for model in LEGS.values():
        for task in TASKS:
            c = clf[(model, task)]
            b = timing["baselines"][task]
            ctx = [float(outcomes[(model, cond, task)]["context_tokens_median"]) for cond in CONDS]
            cost = [per_cand(model, cond, task) for cond in CONDS]
            cin = statistics.median(x["in"] for x in c)
            cout = statistics.median(x["out"] for x in c)
            cusd = statistics.mean(x["usd"] for x in c)
            clat = statistics.median(x["latency_ms"] for x in c)
            cy = cypher_ms(model, task)
            md.append(
                f"| {MODEL_LABEL[model]} | {task} | {project_of[task]} | {cin:.0f} / {cout:.0f}, "
                f"{usd(cusd)}, {clat / 1000:.1f} s | {cy:.1f} ms | {b['bm25_cold']['median_ms']:.0f} ms | "
                f"{b['dense_cached']['median_ms']:.0f} ms | "
                + " / ".join(f"{x:,.0f}" for x in ctx) + " | " + " / ".join(f"{x:.4f}" for x in cost) + " |"
            )
            csv_rows.append({
                "section": "per_task", "model": model, "task": task, "repo": project_of[task],
                "classifier_in": cin, "classifier_out": cout, "classifier_usd": round(cusd, 6),
                "classifier_latency_ms": clat, "cypher_ms": cy,
                "bm25_index_rank_ms": b["bm25_cold"]["median_ms"], "dense_rank_ms": b["dense_cached"]["median_ms"],
                **{f"context_{COND_LABEL[k]}": v for k, v in zip(CONDS, ctx)},
                **{f"usd_per_candidate_{COND_LABEL[k]}": round(v, 6) for k, v in zip(CONDS, cost)},
            })
    md += [
        "",
        "Per task, the KG's retrieval time is dominated by the classifier LLM call (seconds); its Cypher "
        "is milliseconds, comparable to BM25 and dense ranking. The generator call dominates everything.",
    ]

    # ---- 4. Break-even ----
    def mean_cost(model, cond, tasks) -> float:
        return statistics.mean(per_cand(model, cond, t) for t in tasks)

    def pass_rate(model, cond, tasks) -> float:
        return sum(int(outcomes[(model, cond, t)]["passed"]) for t in tasks) / (N_PER_CELL * len(tasks))

    def breakeven(e_kg, i_base, c_kg, c_base) -> float | None:
        """Tasks N with e_kg + N c_kg = i_base + N c_base; None if the KG never catches up."""
        saving = c_base - c_kg
        return (e_kg - i_base) / saving if saving > 0 else None

    def fmt_n(n) -> str:
        return "never" if n is None else f"{n:,.0f}"

    md += [
        "",
        "## 4. Break-even",
        "",
        "**Question (R3):** after how many tasks on a repo does the one-time KG construction cost pay for "
        "itself through cheaper tasks? Amortised against amortised: each side pays its one-time index cost "
        "once, then a per-task cost.",
        "",
        "`N* = (E_KG − I_base) / (c_base − c_KG)`, where `E_KG` is the repo's extraction cost (section 1), "
        "`I_base` the baseline's index cost (BM25 $0; dense section 2), and `c` the mean USD per candidate "
        "over the repo's WP5 tasks (section 3; generator plus, for the KG, classifier; for dense, a query "
        "embedding is added per candidate, since WP5's queries were cache hits).",
        "",
        "**Assumptions:**",
        "",
        "1. The KG is built once with Claude Sonnet 4.6 and reused unchanged by every task and by either "
        "generator; the Qwen rows use the same Claude extraction cost.",
        "2. The code base does not change between tasks. Real repos change, so the KG (and the dense index) "
        "would need re-extraction of the changed files. Incremental re-extraction is future work; at "
        "$0.10–0.15 per file, a change touching k files costs about k × that per re-build.",
        "3. Future tasks cost what the WP5 tasks on that repo cost, per candidate. Six tasks on two repos "
        "is a small basis; the per-task figures are means, not a distribution.",
        "4. Baseline contexts are capped at 7,000 tokens, so their per-task cost does not grow with the repo, "
        "while extraction cost grows with file count. For the three repos without WP5 tasks, the per-task "
        "costs are the pooled means over all six tasks — **extrapolated, and marked so**.",
        "5. Prices as dated above, with no prompt caching. Claude had none. Two OpenRouter providers "
        "applied automatic cache discounts to Qwen calls, so the Qwen USD is an upper bound (billed was 68% "
        "of it over 18–19 Sep; `wp9_phase2_cost.md`, reconciliation). Discounts would shrink both sides of the "
        "Qwen comparison, not only the KG's.",
        "",
        "### 4a. Per candidate (cost only)",
        "",
        "| Model | Repo | E_KG | c_KG | c_BM25 | c_dense | N* vs BM25 | N* vs dense | Basis |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for model in LEGS.values():
        for r in ext:
            repo = r["repo"]
            tasks = [t for t in TASKS if project_of[t] == repo]
            basis = f"{', '.join(tasks)} on this repo" if tasks else "pooled P1–P6 (extrapolated)"
            tasks = tasks or TASKS
            q = dense.get(repo, {}).get("query_usd_median", statistics.median(d["query_usd_median"] for d in dense.values()))
            i_dense = dense[repo]["doc_usd"] if repo in dense else priced(
                EMBED_MODEL, int(statistics.mean(d["doc_tokens"] / ext_by_repo[p]["files"] for p, d in dense.items())
                                 * r["files"]), 0)
            c_kg, c_bm, c_de = (mean_cost(model, "kg_augmented", tasks), mean_cost(model, "bm25", tasks),
                                mean_cost(model, "text_emb_3_large", tasks) + q)
            n_bm, n_de = breakeven(r["usd"], 0.0, c_kg, c_bm), breakeven(r["usd"], i_dense, c_kg, c_de)
            md.append(f"| {MODEL_LABEL[model]} | {repo} | {usd(r['usd'])} | {c_kg:.4f} | {c_bm:.4f} | {c_de:.4f} | "
                      f"**{fmt_n(n_bm)}** | **{fmt_n(n_de)}** | {basis} |")
            csv_rows.append({"section": "breakeven_cost", "model": model, "repo": repo, "e_kg": round(r["usd"], 4),
                             "i_dense": round(i_dense, 6), "c_kg": round(c_kg, 6), "c_bm25": round(c_bm, 6),
                             "c_dense": round(c_de, 6), "n_vs_bm25": n_bm, "n_vs_dense": n_de, "basis": basis})

    md += [
        "",
        "### 4b. Per passing candidate (cost and success)",
        "",
        "Cheaper tasks are only a saving if they succeed as often. Dividing each per-candidate cost by the "
        "condition's WP5 pass rate on the same tasks gives the cost per passing candidate. This treats "
        "attempts as independent retries, which at temperature 0 they are not (a cell's 5 candidates are "
        "near-identical), so it is an illustration of the direction, not a retry-cost model.",
        "",
        "| Model | Tasks | Pass rate KG / BM25 / dense | Per pass KG / BM25 / dense | "
        "N* vs BM25 (react-shopping-cart / takenote) | N* vs dense (react-shopping-cart / takenote) |",
        "|---|---|---|---|---|---|",
    ]
    for model in LEGS.values():
        for label, tasks in [("all six", TASKS)]:
            pr = [pass_rate(model, c, tasks) for c in CONDS]
            per_pass = [mean_cost(model, c, tasks) / p if p else float("inf") for c, p in zip(CONDS, pr)]
            nb, nd = [], []
            for repo in ("react-shopping-cart", "takenote"):
                rt = [t for t in TASKS if project_of[t] == repo]
                prr = [pass_rate(model, c, rt) for c in CONDS]
                cp = [mean_cost(model, c, rt) / p if p else float("inf") for c, p in zip(CONDS, prr)]
                cp[2] += dense[repo]["query_usd_median"] / prr[2] if prr[2] else 0
                e = ext_by_repo[repo]["usd"]
                nb.append(fmt_n(breakeven(e, 0.0, cp[0], cp[1])))
                nd.append(fmt_n(breakeven(e, dense[repo]["doc_usd"], cp[0], cp[2])))
            md.append(
                f"| {MODEL_LABEL[model]} | {label} | " + " / ".join(f"{p:.0%}" for p in pr) + " | "
                + " / ".join(f"{x:.4f}" for x in per_pass) + f" | {' / '.join(nb)} | {' / '.join(nd)} |"
            )

    cl, qw = LEGS["claude_primary"], LEGS["qwen_robustness"]
    c = {m: {k: mean_cost(m, k, TASKS) for k in CONDS} for m in (cl, qw)}
    ctx = {k: [float(outcomes[(cl, k, t)]["context_tokens_median"]) for t in TASKS] for k in CONDS}
    base_ctx = ctx["bm25"] + ctx["text_emb_3_large"]
    n_rows = [r for r in csv_rows if r["section"] == "breakeven_cost" and r["basis"].endswith("this repo")]
    n_range = {m: [n for r in n_rows if r["model"] == m for n in (r["n_vs_bm25"], r["n_vs_dense"]) if n]
               for m in (cl, qw)}
    passes = {m: {k: sum(int(outcomes[(m, k, t)]["passed"]) for t in TASKS) for k in CONDS} for m in (cl, qw)}
    i_dense = [d["doc_usd"] for d in dense.values()]
    md += [
        "",
        "### Statement",
        "",
        f"- **Per task, the KG condition is the cheapest retrieval condition.** A KG candidate costs "
        f"{usd(c[cl]['kg_augmented'])} with Claude, against {usd(c[cl]['bm25'])} (BM25) and "
        f"{usd(c[cl]['text_emb_3_large'])} (dense); with Qwen {usd(c[qw]['kg_augmented'])} against "
        f"{usd(c[qw]['bm25'])} and {usd(c[qw]['text_emb_3_large'])}. The KG context is "
        f"{min(ctx['kg_augmented']):,.0f}–{max(ctx['kg_augmented']):,.0f} tokens, the capped baseline contexts "
        f"{min(base_ctx):,.0f}–{max(base_ctx):,.0f}. The classifier adds about "
        f"{usd(statistics.mean(x['usd'] for t in TASKS for x in clf[(cl, t)]))} (Claude) per task.",
        f"- **The KG's one-time cost is about three orders of magnitude above the baselines'.** Extraction "
        f"costs {usd(min(r['usd'] for r in ext))}–{usd(max(r['usd'] for r in ext))} per repo "
        f"({usd(min(r['usd_per_source_file'] for r in ext))}–{usd(max(r['usd_per_source_file'] for r in ext))} "
        f"per source file); the dense index {usd(min(i_dense))}–{usd(max(i_dense))}; BM25 nothing.",
        f"- **Break-even, on the two repos with tasks, is {min(n_range[cl]):,.0f}–{max(n_range[cl]):,.0f} tasks "
        f"with Claude and {min(n_range[qw]):,.0f}–{max(n_range[qw]):,.0f} with Qwen** (4a). It grows linearly "
        "with repo size, since baseline contexts are capped (extrapolated rows in 4a). Counting success (4b) "
        "moves these figures in both directions, without changing their order of magnitude.",
        f"- **What the KG buys is smaller, cheaper prompts, not higher pass rates** in this study: out of "
        f"{N_PER_CELL * len(TASKS)}, the KG passed {passes[cl]['kg_augmented']} (Claude) and "
        f"{passes[qw]['kg_augmented']} (Qwen), BM25 {passes[cl]['bm25']} and {passes[qw]['bm25']}, dense "
        f"{passes[cl]['text_emb_3_large']} and {passes[qw]['text_emb_3_large']} (`wp5_outcomes.md`).",
        "- The construction cost is paid by the extraction model (Claude) whatever the generator. A cheaper "
        "generator shrinks the per-task saving, so with Qwen the KG pays back about ten times more slowly.",
        "- Time: extraction takes minutes to an hour per repo, once; per task, KG retrieval adds one "
        "classifier call (seconds) and milliseconds of Cypher, while BM25 and dense rank in tens of ms.",
    ]

    OUT.with_suffix(".md").write_text("\n".join(md) + "\n", encoding="utf-8")
    all_rows = [{"section": "extraction", **r} for r in ext] + csv_rows
    fields = sorted({k for r in all_rows for k in r}, key=lambda k: (k != "section", k))
    with OUT.with_suffix(".csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(all_rows)
    print("\n".join(md))
    print(f"\nwrote {OUT.with_suffix('.md')} and {OUT.with_suffix('.csv')}")


if __name__ == "__main__":
    main()
