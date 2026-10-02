"""Dense retriever — the embedding baseline (IJCKG revision WP3).

Condition `text_emb_3_large` of the baseline ladder (`phase2_design_summary.md`).
Plan: `docs/phase_2/ijckg-2026/wp3_dense_plan.md`.

Differs from the BM25 baseline (`bm25_retriever.py`) **only in how files are
scored**. Everything else is imported from it, not re-implemented:

- **Corpus and chunk:** `build_corpus()` — the KG's own file set with the
  project's `exclude_paths`, one chunk per file. Every file in both Docker repos
  is under 4k tokens, inside the embedding model's 8,191-token input limit, so no
  file is split.
- **Fill:** `select_within_budget()` (first-fit whole files within the KG
  assembler's `DEFAULT_TOKEN_BUDGET` and `_estimate_tokens`), then the same
  rendered-cap drop loop. Its `score <= 0` stop only drops negative cosines, which
  do not occur in practice, so dense **fills the budget**. BM25 stops at files
  sharing no word with the spec; dense has no such zero.

Embedding:

- **Text embedded:** documents as `"{path}\\n{source}"` (BM25 indexes the path
  too); the query is the task spec verbatim.
- **Model:** `[retriever_params] embedding_model` in the condition TOML, full
  dimensions. Fixed across generator models: the open-weight leg uses the same
  OpenAI embedder, so it is not embedding-model-pure.
- **Scoring:** cosine similarity; ties broken by path.
- **Cache (committed):** `embedding_cache/<project>/<model>.jsonl`, one line per
  text, keyed on `sha256(model + "\\0" + text)`, vector stored as float32 base64.
  OpenAI embeddings are not bit-reproducible across calls, so **the committed
  cache is what makes runs repeatable**: every candidate of a cell sees the same
  vectors. Vectors are always cast to float32 before use, so a run that fills the
  cache ranks exactly as a run that reads it. Content-keyed, so an edited file
  misses rather than reusing a stale vector. On a duplicate key the first line
  wins. Each row carries its API call's `batch` (`id`, `size`, `prompt_tokens`),
  so the index's embedding cost can be read from the cache alone (WP9).
- **API calls** happen only for cache misses — all missing documents in batched
  calls, then the query — through `logged_embedding_call()`, which logs token
  usage for WP9 (`call_purpose` `embedding_index` / `embedding_query`). A lock per
  cache file makes concurrent candidates of one run share one call per text.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import uuid
import weakref
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from src.llm.logger import logged_embedding_call
from src.retrieval.assembler import DEFAULT_TOKEN_BUDGET, _estimate_tokens
from src.retrieval.base import Retriever
from src.retrieval.bm25_retriever import TOP_N_METADATA, _Doc, build_corpus, select_within_budget
from src.retrieval.config import RetrievalConditionConfig
from src.retrieval.models import ComponentContext, ContextData, RetrievalResult, RoundRecord
from src.retrieval.renderer import ContextRenderer

DEFAULT_EMBEDDING_MODEL = "text-embedding-3-large"
DEFAULT_CACHE_ROOT = Path("embedding_cache")
# Inputs per API request. OpenAI allows 2,048 inputs and 300k tokens per request;
# 64 whole files stays far below the token limit on these repos.
BATCH_SIZE = 64

QUERY_LABEL = "<spec>"


def cache_key(model: str, text: str) -> str:
    return hashlib.sha256(f"{model}\0{text}".encode("utf-8")).hexdigest()


def doc_text(doc: _Doc) -> str:
    return f"{doc.path}\n{doc.source}"


def _encode(vec: np.ndarray) -> str:
    return base64.b64encode(np.asarray(vec, dtype="<f4").tobytes()).decode("ascii")


def _decode(b64: str) -> np.ndarray:
    return np.frombuffer(base64.b64decode(b64), dtype="<f4").copy()


class EmbeddingCache:
    """Append-only JSONL of embeddings for one (project, model)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._vectors: dict[str, np.ndarray] = {}
        if path.exists():
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    self._vectors.setdefault(row["key"], _decode(row["embedding_b64"]))

    def get(self, key: str) -> np.ndarray | None:
        return self._vectors.get(key)

    def __len__(self) -> int:
        return len(self._vectors)

    def add(self, rows: list[dict]) -> list[np.ndarray]:
        """Append rows (`key`, `kind`, `label`, `batch`, `vector`); return float32 vectors.

        `batch` is `{id, size, prompt_tokens}` of the API call that produced the row.
        The API reports tokens per call, not per input, so the index's cost is the
        sum of `prompt_tokens` over distinct batch ids — readable from the cache
        alone, whichever run built it.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        created = datetime.now(timezone.utc).isoformat()
        out = []
        with open(self.path, "a", encoding="utf-8") as f:
            for row in rows:
                vec = np.asarray(row["vector"], dtype="<f4")
                self._vectors.setdefault(row["key"], vec)
                out.append(self._vectors[row["key"]])
                f.write(json.dumps({
                    "key": row["key"],
                    "kind": row["kind"],
                    "label": row["label"],
                    "batch": row["batch"],
                    "created": created,
                    "embedding_b64": _encode(vec),
                }) + "\n")
            f.flush()
        return out


# Per event loop, then per cache file. An asyncio.Lock binds to the loop it is
# first used on, so locks must not outlive their loop; keying on the loop object
# weakly (not on `id(loop)`, which a later loop can reuse) frees them with it.
_LOCKS: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Lock]] = (
    weakref.WeakKeyDictionary()
)


def _lock_for(path: Path) -> asyncio.Lock:
    per_loop = _LOCKS.setdefault(asyncio.get_running_loop(), {})
    return per_loop.setdefault(str(path.resolve()), asyncio.Lock())


def rank_by_cosine(query: np.ndarray, docs: tuple[_Doc, ...], vectors: list[np.ndarray]) -> list[tuple[_Doc, float]]:
    """All docs with cosine similarity to the query, best first, ties by path."""
    if not docs:
        return []
    matrix = np.stack(vectors).astype(np.float64)
    q = np.asarray(query, dtype=np.float64)
    norms = np.linalg.norm(matrix, axis=1) * np.linalg.norm(q)
    scores = (matrix @ q) / np.where(norms == 0, 1.0, norms)
    return sorted(zip(docs, (float(s) for s in scores)), key=lambda x: (-x[1], x[0].path))


class DenseRetriever(Retriever):
    """File-level cosine ranking over the KG's file set, filled to the KG's token budget."""

    def __init__(
        self,
        config: RetrievalConditionConfig,
        *,
        run_id: str,
        task_type: str = "",
        project_name: str = "",
        exclude_paths: list[str] | None = None,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
        cache_root: Path | None = None,
        log_dir: Path | None = None,
    ) -> None:
        super().__init__(config)
        self.run_id = run_id
        # task_type comes from the task YAML, as for WholeFileRetriever and BM25;
        # it only fills Format A's "Task type" header line.
        self.task_type = task_type
        self.project_name = project_name
        self.exclude_paths = tuple(exclude_paths or ())
        self.token_budget = token_budget
        self.cache_root = Path(cache_root) if cache_root is not None else DEFAULT_CACHE_ROOT
        self.log_dir = log_dir
        self.model = config.retriever_params.get("embedding_model", DEFAULT_EMBEDDING_MODEL)

    def _cache_path(self, repo_root: Path) -> Path:
        return self.cache_root / (self.project_name or repo_root.name) / f"{self.model}.jsonl"

    async def _embed(
        self, cache: EmbeddingCache, items: list[tuple[str, str, str]], call_purpose: str, stats: dict
    ) -> list[np.ndarray]:
        """Vectors for (kind, label, text) items: cache first, API for the misses."""
        keys = [cache_key(self.model, text) for _, _, text in items]
        missing = [i for i, k in enumerate(keys) if cache.get(k) is None]
        stats["cache_hits"] += len(items) - len(missing)
        if missing and not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError(
                f"Dense retrieval needs {len(missing)} new embedding(s) from {self.model} but "
                f"OPENAI_API_KEY is not set. Set it in .env / the shell (needed in every leg, "
                f"whatever the generator model), or commit a cache covering these texts."
            )
        for start in range(0, len(missing), BATCH_SIZE):
            batch = missing[start:start + BATCH_SIZE]
            resp = await logged_embedding_call(
                texts=[items[i][2] for i in batch],
                labels=[items[i][1] for i in batch],
                model=self.model,
                run_id=self.run_id,
                condition_id=self.config.condition_id,
                call_purpose=call_purpose,
                log_dir=self.log_dir,
            )
            stats["api_calls"] += 1
            stats["api_prompt_tokens"] += resp.prompt_tokens or 0
            batch_info = {"id": uuid.uuid4().hex, "size": len(batch), "prompt_tokens": resp.prompt_tokens}
            cache.add([
                {"key": keys[i], "kind": items[i][0], "label": items[i][1],
                 "batch": batch_info, "vector": vec}
                for i, vec in zip(batch, resp.vectors)
            ])
        return [cache.get(k) for k in keys]

    def _render(self, spec: str, included: list[_Doc]) -> str:
        context_data = ContextData(
            task_spec=spec,
            task_type=self.task_type,
            target_components=[
                ComponentContext(
                    name=Path(d.path).stem,
                    file_path=d.path,
                    source_code=d.source,
                    component_type="file",
                )
                for d in included
            ],
            project_name=self.project_name,
            retriever_name="dense",
        )
        return ContextRenderer().render(self.config.format_variant, context_data)

    async def retrieve(
        self,
        spec: str,
        project_id: str,
        repo_root: str | Path,
        max_rounds: int = 1,
    ) -> RetrievalResult:
        root = Path(repo_root).resolve()
        docs = build_corpus(str(root), self.exclude_paths)
        cache_path = self._cache_path(root)
        stats = {"cache_hits": 0, "api_calls": 0, "api_prompt_tokens": 0}

        async with _lock_for(cache_path):
            cache = EmbeddingCache(cache_path)
            doc_vecs = await self._embed(
                cache, [("doc", d.path, doc_text(d)) for d in docs], "embedding_index", stats
            )
            (query_vec,) = await self._embed(
                cache, [("query", QUERY_LABEL, spec)], "embedding_query", stats
            )

        ranked = rank_by_cosine(query_vec, docs, doc_vecs)
        included, skipped, used = select_within_budget(ranked, spec, self.token_budget)

        # Enforce the cap on the rendered context, not only on spec + source.
        context = self._render(spec, included)
        while included and _estimate_tokens(context) > self.token_budget:
            dropped = included.pop()
            skipped.append(dropped.path)
            used -= _estimate_tokens(dropped.source)
            context = self._render(spec, included)
        retrieved = [d.path for d in included]

        return RetrievalResult(
            context=context,
            rounds=[
                RoundRecord(
                    round_number=1,
                    query=spec,
                    retrieved_files=retrieved,
                    context_snippet=context[:500],
                    token_count=_estimate_tokens(context),
                )
            ],
            retriever_name="dense",
            condition_id=self.config.condition_id,
            total_token_count=_estimate_tokens(context),
            metadata={
                "embedding_model": self.model,
                "cache_file": str(cache_path),
                "corpus_size": len(docs),
                "ranked_top": [
                    {"path": d.path, "score": round(s, 6)} for d, s in ranked[:TOP_N_METADATA]
                ],
                "included_files": retrieved,
                "skipped_for_budget": skipped,
                "budget_tokens_used": used,
                "token_budget": self.token_budget,
                **stats,
            },
        )
