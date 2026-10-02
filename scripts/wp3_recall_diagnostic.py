"""File-level recall@budget, dense vs BM25 (IJCKG WP3 diagnostic; no LLM, no Docker).

All six tasks read their statement from tasks/pilot/<id>.yaml through the
orchestrator's own loader, so the query text is byte-identical to the runs'
(stripped; the 18 Sep version passed the YAML's trailing newline and ranked with
slightly different query vectors). Dense reads embedding_cache/; a new
statement is embedded and logged under experiment_logs/wp3_dense_diagnostic/.
Run: uv run python scripts/wp3_recall_diagnostic.py
"""
import asyncio
from src.config import get_settings
from src.generation.orchestrator import load_task_spec, _load_task_yaml, resolve_repo_root
from src.retrieval.bm25_retriever import BM25Retriever
from src.retrieval.dense_retriever import DenseRetriever
from src.retrieval.config import RetrievalConditionConfig
from src.retrieval.assembler import _estimate_tokens

bcfg = RetrievalConditionConfig(condition_id="bm25", retriever="bm25", format_variant="A")
dcfg = RetrievalConditionConfig(condition_id="text_emb_3_large", retriever="text_emb_3_large", format_variant="A",
                                retriever_params={"embedding_model": "text-embedding-3-large"})

def rank_of(md, f, corpus):
    top = [x["path"] for x in md["ranked_top"]]
    return top.index(f) + 1 if f in top else f">{len(top)}"

async def main():
    tasks = {}
    for t in ["P1","P2","P3","P4","P5","P6"]:
        y = _load_task_yaml(t)
        tasks[t] = (y["project_id"], load_task_spec(t), y["files_modified"])
    print("| Task | Needed file | Dense rank | Dense in | BM25 rank | BM25 in | Dense tok / files | BM25 tok / files |")
    print("|---|---|---|---|---|---|---|---|")
    api = 0
    for t, (proj, spec, needed) in tasks.items():
        excl = get_settings().projects[proj].exclude_paths
        root = resolve_repo_root(proj)
        d = await DenseRetriever(dcfg, run_id="wp3_dense_diagnostic", project_name=proj, exclude_paths=excl).retrieve(spec, "", root)
        b = await BM25Retriever(bcfg, project_name=proj, exclude_paths=excl).retrieve(spec, "", root)
        api += d.metadata["api_prompt_tokens"]
        dm, bm = d.metadata, b.metadata
        dsz = f"{d.total_token_count:,} / {len(dm['included_files'])}"
        bsz = f"{b.total_token_count:,} / {len(bm['included_files'])}"
        for i, f in enumerate(needed):
            first = i == 0
            din = "yes" if f in dm["included_files"] else "**no**"
            bin_ = "yes" if f in bm["included_files"] else "**no**"
            print(f"| {t if first else ''} | `{f.split('/')[-1]}` | {rank_of(dm, f, 0)} | {din} | "
                  f"{rank_of(bm, f, 0)} | {bin_} | {dsz if first else ''} | {bsz if first else ''} |")
        print(f"<!-- {t}: dense top5 {[x['path'].split('/')[-1] for x in dm['ranked_top'][:5]]} -->")
    print(f"<!-- new query embedding tokens this run: {api} -->")
asyncio.run(main())
