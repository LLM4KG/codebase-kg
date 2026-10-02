"""BM25 retriever — the sparse lexical baseline (IJCKG revision WP2).

Condition 3 of the baseline ladder (`phase2_design_summary.md`): "file-level chunks
scored against the spec, top-k filling the budget". No LLM call and no KG query,
so retrieval-side LLM cost is zero by construction.

Design choices, each fixed so the comparison with KG-augmented varies in one thing
only — *how files are chosen* (see `docs/phase_2/ijckg-2026/wp2_bm25_plan.md`):

- **Corpus = the KG's own file set.** `extract_files()` with the project's
  `exclude_paths`, exactly what Stage 1 of extraction indexed. BM25 can never see a
  file the KG could not, nor miss one it could. One chunk per file.
- **Code-aware tokenizer**, shared by query and documents: split on non-alphanumerics,
  split camelCase/PascalCase, lowercase, keep the whole identifier alongside its
  parts (so an exact symbol match outranks a partial one), drop a small stopword
  list. A document also includes its own path — `cart-context` is real signal.
- **Scorer:** `rank_bm25.BM25Okapi` term weighting with library defaults (k1=1.5,
  b=0.75), but with the **Lucene/Elasticsearch IDF** `log(1 + (N-n+0.5)/(n+0.5))`
  instead of the library's. The library floors any word in more than half the files
  at `0.25 * mean IDF`, which on these corpora is *higher* than the IDF of moderately
  common words: `src` (60/60 TakeNote files) weighed 0.74 against `notes` (26/60)
  at 0.26. That made every file score above zero and tilted ranking toward files
  with many import paths. Lucene's form is positive and strictly decreasing in `n`.
  Ranking is by score descending, ties broken by path, so the output is deterministic.
- **Budget:** the KG assembler's own `DEFAULT_TOKEN_BUDGET` and `_estimate_tokens`,
  imported, never re-implemented (ground rule 2). Used budget = spec + included
  sources, the same quantities the KG assembler counts.
- **Fill:** whole files in rank order — truncated source would break
  `search_replace` matching. A file that would overflow is skipped and filling
  continues (first-fit), so one large file cannot starve the context. Files sharing
  no word with the spec score zero and are never included. After the rendered-cap
  drop below, files skipped earlier are not re-tried (at most one file is affected).
- **The cap holds on what the model sees.** Rendering adds a heading and a code
  fence per file, which the spec + source count does not see (P2/P3/P6 rendered at
  ~7,035). After rendering, the lowest-ranked included file is dropped until the
  rendered estimate is within budget. The KG's contexts sit far below the cap, so
  for them the two accountings never diverge.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from rank_bm25 import BM25Okapi

from src.extraction.programmatic import extract_files
from src.retrieval.assembler import DEFAULT_TOKEN_BUDGET, _estimate_tokens, _read_source
from src.retrieval.base import Retriever
from src.retrieval.config import RetrievalConditionConfig
from src.retrieval.models import ComponentContext, ContextData, RetrievalResult, RoundRecord
from src.retrieval.renderer import ContextRenderer

logger = logging.getLogger(__name__)

TOP_N_METADATA = 20

# Deliberately small: common English words from task statements. Code keywords
# (`const`, `return`, `import`) are left in — BM25's IDF already discounts words
# that occur in every file, and a hand-tuned code stoplist would be a second
# variable in the comparison.
STOPWORDS = frozenset(
    """a an and are as at be but by for from has have if in into is it its not of on or
    so that the then there these this to was when which while will with""".split()
)

_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")
# Boundaries inside an identifier: fooBar -> foo|Bar, HTTPServer -> HTTP|Server, v2Api -> v2|Api
_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")


def tokenize(text: str) -> list[str]:
    """Lowercased tokens: each identifier plus its camelCase parts, minus stopwords."""
    tokens: list[str] = []
    for word in _NON_ALNUM.split(text):
        if not word:
            continue
        parts = _CAMEL.findall(word)
        if len(parts) > 1:
            tokens.append(word.lower())
        tokens.extend(p.lower() for p in parts)
    # One-character tokens are noise, not signal: `product's` -> `s`, `$0.00` -> `0`.
    return [t for t in tokens if len(t) > 1 and t not in STOPWORDS]


class LuceneBM25(BM25Okapi):
    """BM25Okapi with Lucene's IDF, `log(1 + (N - n + 0.5) / (n + 0.5))`.

    Always positive and strictly decreasing in document frequency `n`, unlike
    rank_bm25's own IDF, which is negative above n = N/2 and then floored at a
    constant that can exceed the IDF of rarer words.
    """

    def _calc_idf(self, nd):
        for word, freq in nd.items():
            self.idf[word] = math.log(1 + (self.corpus_size - freq + 0.5) / (freq + 0.5))
        self.average_idf = sum(self.idf.values()) / len(self.idf) if self.idf else 0.0


@dataclass(frozen=True)
class _Doc:
    path: str
    source: str


@lru_cache(maxsize=8)
def build_corpus(repo_root: str, exclude_paths: tuple[str, ...] = ()) -> tuple[_Doc, ...]:
    """The KG's file set for this repo, with source. Cached per (repo, excludes)."""
    root = Path(repo_root)
    docs = []
    for entry in extract_files(root, list(exclude_paths)):
        source = _read_source(root, entry["filePath"])
        if source is not None:
            docs.append(_Doc(entry["filePath"], source))
    return tuple(docs)


def rank(spec: str, docs: tuple[_Doc, ...]) -> list[tuple[_Doc, float]]:
    """All docs with their BM25 score for the spec, best first, ties by path."""
    if not docs:
        return []
    bm25 = LuceneBM25([tokenize(f"{d.path} {d.source}") for d in docs])
    scores = bm25.get_scores(tokenize(spec))
    ranked = sorted(zip(docs, (float(s) for s in scores)), key=lambda x: (-x[1], x[0].path))
    return ranked


def select_within_budget(
    ranked: list[tuple[_Doc, float]], spec: str, budget: int = DEFAULT_TOKEN_BUDGET
) -> tuple[list[_Doc], list[str], int]:
    """First-fit whole files in rank order. Returns (included, skipped paths, tokens used)."""
    used = _estimate_tokens(spec)
    included: list[_Doc] = []
    skipped: list[str] = []
    for doc, score in ranked:
        if score <= 0:
            break
        cost = _estimate_tokens(doc.source)
        if used + cost > budget:
            skipped.append(doc.path)
            continue
        included.append(doc)
        used += cost
    return included, skipped, used


class BM25Retriever(Retriever):
    """File-level BM25 over the KG's file set, filled to the KG's token budget."""

    def __init__(
        self,
        config: RetrievalConditionConfig,
        *,
        task_type: str = "",
        project_name: str = "",
        exclude_paths: list[str] | None = None,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
    ) -> None:
        super().__init__(config)
        # task_type comes from the task YAML, as for WholeFileRetriever; it only
        # fills Format A's "Task type" header line.
        self.task_type = task_type
        self.project_name = project_name
        self.exclude_paths = tuple(exclude_paths or ())
        self.token_budget = token_budget

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
            retriever_name="bm25",
        )
        return ContextRenderer().render(self.config.format_variant, context_data)

    async def retrieve(
        self,
        spec: str,
        project_id: str,
        repo_root: str | Path,
        max_rounds: int = 1,
    ) -> RetrievalResult:
        docs = build_corpus(str(Path(repo_root).resolve()), self.exclude_paths)
        ranked = rank(spec, docs)
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
            retriever_name="bm25",
            condition_id=self.config.condition_id,
            total_token_count=_estimate_tokens(context),
            metadata={
                "query_tokens": tokenize(spec),
                "corpus_size": len(docs),
                "ranked_top": [
                    {"path": d.path, "score": round(s, 4)} for d, s in ranked[:TOP_N_METADATA]
                ],
                "included_files": retrieved,
                "skipped_for_budget": skipped,
                "budget_tokens_used": used,
                "token_budget": self.token_budget,
            },
        )
