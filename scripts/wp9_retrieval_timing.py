"""WP9: retrieval-side time per task — Cypher query time for the KG, index + rank for the baselines.

Cypher time is not logged by the WP5 runs, so it is measured here by replaying them:
every classifier output logged in the WP5 KG runs (both models, P1-P6) is parsed back
into a ClassifierResult and dispatched through `KGAugmentedRetriever._dispatch`, the
code path WP5 used, against the committed graph of record loaded into Memgraph. No
LLM or embedding call is made.

Measured, per distinct (task, classification):
  - each Cypher template's execution time (primary, routing / caller-props, neighbour props);
  - the whole dispatch (Cypher + disk reads + assembly).
Per task, for the baselines (same corpus and cap as WP5):
  - BM25: retrieve() cold (files read + index built) and warm (index built + ranked;
    BM25Retriever builds its index per call and caches only the file read);
  - dense: retrieve() from the committed embedding cache (0 API calls, checked), on a
    temporary copy so the committed cache is never written.
Per repo: the one-time KG load (import of full_dump.cypherl).

Timings are wall-clock on this host, median of REPS after WARMUP; the host is
recorded. Point the pipeline at the scratch Memgraph, never the main one:

    PIPELINE_DB__URI=bolt://localhost:7688 uv run python scripts/wp9_retrieval_timing.py

Writes docs/phase_2/ijckg-2026/wp9_retrieval_timing.json.
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import shutil
import statistics
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import get_settings  # noqa: E402
from src.evaluation.cost import match_task  # noqa: E402
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
from src.retrieval import bm25_retriever  # noqa: E402
from src.retrieval.bm25_retriever import BM25Retriever  # noqa: E402
from src.retrieval.classifier import parse_classifier_response  # noqa: E402
from src.retrieval.config import load_experiment_config  # noqa: E402
from src.retrieval.dense_retriever import DenseRetriever  # noqa: E402
from src.retrieval.kg_retriever import KGAugmentedRetriever  # noqa: E402

LOGS = Path("experiment_logs")
OUT = Path("docs/phase_2/ijckg-2026/wp9_retrieval_timing.json")
TASKS = ["P1", "P2", "P3", "P4", "P5", "P6"]
KG_RUNS = {
    "anthropic/claude-sonnet-4-6": ["claude_primary_2026-09-18_wp5_p1p3", "claude_primary_2026-09-19_wp5_p4p6"],
    "openrouter/qwen/qwen3-coder": ["qwen_robustness_2026-09-18_wp5_p1p3", "qwen_robustness_2026-09-19_wp5_p4p6"],
}
WARMUP, REPS, LOAD_REPS = 3, 30, 3


def ms(seconds: list[float]) -> dict:
    v = [s * 1000 for s in seconds]
    return {"median_ms": round(statistics.median(v), 3), "min_ms": round(min(v), 3),
            "max_ms": round(max(v), 3), "n": len(v)}


def logged_classifications(specs: dict[str, str]) -> dict[tuple[str, str, str], dict]:
    """(model, task, classification JSON) -> {result, calls} from the WP5 KG logs."""
    out: dict[tuple[str, str, str], dict] = {}
    for model, runs in KG_RUNS.items():
        for run in runs:
            path = LOGS / run / "kg_augmented.jsonl"
            if not path.exists():
                sys.exit(f"missing {path}")
            for line in path.open(encoding="utf-8"):
                rec = json.loads(line)
                if rec.get("call_purpose") != "classifier":
                    continue
                task = match_task(rec, specs)
                if task is None:
                    sys.exit(f"{run}: classifier call matches no task")
                result = parse_classifier_response(rec.get("response") or "")
                key = (model, task, result.model_dump_json())
                out.setdefault(key, {"result": result, "calls": 0})["calls"] += 1
    return out


def load_kg(project: str) -> tuple[str, list[float]]:
    """Wipe and import the project's dump LOAD_REPS times; return projectId and timings."""
    dump = GRAPH_EXPORT_DIR / project / "full_dump.cypherl"
    times = []
    for _ in range(LOAD_REPS):
        wipe_database()
        t0 = time.perf_counter()
        import_cypherl(dump)
        times.append(time.perf_counter() - t0)
    return resolve_project_id(project), times


async def time_kg(retriever: KGAugmentedRetriever, result, project_id: str, repo_root: Path) -> dict:
    per_query: dict[str, list[float]] = {}
    rows_by_query: dict[str, int] = {}
    original = retriever._run_query

    async def timed(name: str, params: dict) -> list[dict]:
        t0 = time.perf_counter()
        rows = await original(name, params)
        per_query.setdefault(name, []).append(time.perf_counter() - t0)
        rows_by_query[name] = len(rows)
        return rows

    retriever._run_query = timed
    dispatch = []
    for i in range(WARMUP + REPS):
        t0 = time.perf_counter()
        await retriever._dispatch(result, project_id, repo_root)
        if i >= WARMUP:
            dispatch.append(time.perf_counter() - t0)
    retriever._run_query = original
    queries = {name: {**ms(ts[WARMUP:]), "rows": rows_by_query[name]} for name, ts in per_query.items()}
    cypher_per_rep = [sum(ts[WARMUP + i] for ts in per_query.values()) for i in range(REPS)]
    return {"queries": queries, "cypher_total": ms(cypher_per_rep), "dispatch_total": ms(dispatch)}


async def time_baselines(task: str, project: str, repo_root: Path, cache_root: Path) -> dict:
    spec = load_task_spec(task)
    task_type = _load_task_yaml(task).get("task_type", "")
    project_cfg = get_settings().projects.get(project)
    excludes = project_cfg.exclude_paths if project_cfg else []
    bm25_cond = load_experiment_config("claude_primary", "bm25").condition
    dense_cond = load_experiment_config("claude_primary", "text_emb_3_large").condition

    def bm25() -> BM25Retriever:
        return BM25Retriever(bm25_cond, task_type=task_type, project_name=project, exclude_paths=excludes)

    cold, warm, dense = [], [], []
    for i in range(WARMUP + REPS):
        bm25_retriever.build_corpus.cache_clear()
        t0 = time.perf_counter()
        await bm25().retrieve(spec, "", repo_root)
        t1 = time.perf_counter()
        await bm25().retrieve(spec, "", repo_root)
        t2 = time.perf_counter()
        r = await DenseRetriever(dense_cond, run_id="wp9_timing", task_type=task_type, project_name=project,
                                 exclude_paths=excludes, cache_root=cache_root).retrieve(spec, "", repo_root)
        t3 = time.perf_counter()
        if r.metadata.get("api_calls") != 0:
            sys.exit(f"{task}: dense made {r.metadata.get('api_calls')} API calls; the cache should cover WP5")
        if i >= WARMUP:
            cold.append(t1 - t0)
            warm.append(t2 - t1)
            dense.append(t3 - t2)
    return {"bm25_cold": ms(cold), "bm25_warm": ms(warm), "dense_cached": ms(dense)}


async def main() -> None:
    uri = get_settings().db.uri
    if not uri.endswith(":7688") and os.environ.get("WP9_ALLOW_MAIN_DB") != "1":
        sys.exit(f"refusing to wipe {uri}: run with PIPELINE_DB__URI=bolt://localhost:7688")

    specs = {t: load_task_spec(t) for t in TASKS}
    classifications = logged_classifications(specs)
    project_of = {t: _task_project(t) for t in TASKS}

    out = {
        "host": {"machine": platform.machine(), "system": platform.system(), "release": platform.release(),
                 "processor": platform.processor(), "python": platform.python_version(),
                 "cpu_count": os.cpu_count(), "db_uri": uri},
        "method": {"warmup": WARMUP, "reps": REPS, "kg_load_reps": LOAD_REPS,
                   "classifications_from": KG_RUNS},
        "kg_load": {}, "kg": [], "baselines": {},
    }
    kg_cond = load_experiment_config("claude_primary", "kg_augmented").condition
    with tempfile.TemporaryDirectory() as tmp:
        cache_root = Path(tmp) / "embedding_cache"
        shutil.copytree("embedding_cache", cache_root)
        for project in sorted(set(project_of.values())):
            repo_root = resolve_repo_root(project)
            project_id, load_times = load_kg(project)
            out["kg_load"][project] = ms(load_times)
            print(f"{project}: KG load {out['kg_load'][project]['median_ms']:.0f} ms", flush=True)
            for (model, task, cls_json), entry in sorted(classifications.items()):
                if project_of[task] != project:
                    continue
                retriever = KGAugmentedRetriever(kg_cond, model=model, run_id="wp9_timing", project_name=project)
                timing = await time_kg(retriever, entry["result"], project_id, repo_root)
                out["kg"].append({"model": model, "task": task, "project": project,
                                  "classification": json.loads(cls_json), "calls": entry["calls"], **timing})
                print(f"  {task} {model.split('/')[-1]} x{entry['calls']}: cypher "
                      f"{timing['cypher_total']['median_ms']:.1f} ms, dispatch "
                      f"{timing['dispatch_total']['median_ms']:.1f} ms", flush=True)
            for task in TASKS:
                if project_of[task] == project:
                    out["baselines"][task] = {"project": project,
                                              **await time_baselines(task, project, repo_root, cache_root)}
                    b = out["baselines"][task]
                    print(f"  {task} bm25 cold {b['bm25_cold']['median_ms']:.1f} / warm "
                          f"{b['bm25_warm']['median_ms']:.1f} ms, dense {b['dense_cached']['median_ms']:.1f} ms",
                          flush=True)
    counts = Counter((k[0], k[1]) for k in classifications)
    out["distinct_classifications"] = {f"{m}|{t}": n for (m, t), n in sorted(counts.items())}
    OUT.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
