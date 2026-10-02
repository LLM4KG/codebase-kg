# WP3 — Dense retriever (text-embedding-3-large): implementation plan

> Written 18 Sep 2026. Referenced from the WP3 section of [`revision_implementation_plan_18-22Sep.md`](revision_implementation_plan_18-22Sep.md).

## Context
WP3 of `docs/phase_2/ijckg-2026/revision_implementation_plan_18-22Sep.md` adds the dense-retrieval
baseline that reviewers R1 and R2 asked for (condition `text_emb_3_large`, config already at
`conditions/base/text_emb_3_large.toml`, no retriever yet). The plan fixes the method: **same
chunking as WP2** so BM25 and dense differ only in how chunks are scored; embeddings through
LiteLLM, cached on disk per repo and committed; cosine ranking; fill to the same 7000-token cap
with the same estimator. Both models' legs use the same OpenAI embedder. Nomic Embed Code is out
of scope.

Measured today: react-shopping-cart = 55 files / 41k chars, TakeNote = 60 files / 153k chars;
largest file `SettingsModal.tsx` 11.5k chars (≈ 3–4k tokens), so every file fits the model's
8,191-token input limit — **no sub-file chunking needed**. Indexing both repos is ≈ 60k tokens
≈ **$0.01** at $0.13/M.

**Blocker:** `OPENAI_API_KEY` is not set in `.env`. Code and unit tests don't need it (the
embedding call is mocked); the cache build, dry run and diagnostic do.

---

## Step 0 — Record the plan (done)
Write this plan to `docs/phase_2/ijckg-2026/wp3_dense_plan.md` and link it from the WP3 section of
the revision plan (as done for WP2/WP4). Commit on its own (`docs(dense)`).

## Design decisions (module docstring + WP3 note)
- **Corpus and chunk = BM25's.** Import `build_corpus`, `_Doc`, `select_within_budget` from
  `src/retrieval/bm25_retriever.py` (the KG's file set with the project's `exclude_paths`, one
  chunk per file). **The reviewed BM25 module is not modified**; dense repeats its ~15-line
  render-and-cap loop rather than refactoring reviewed code.
- **Text embedded:** documents as `f"{path}\n{source}"` (BM25 also indexes the path); the query is
  the task spec verbatim.
- **Model:** `text-embedding-3-large`, full 3,072 dimensions (no `dimensions` truncation), read from
  `[retriever_params] embedding_model` in the TOML so it is recorded with the condition. Fixed
  regardless of the generator model; the Qwen leg is therefore not embedding-model-pure (noted in
  the WP3 note and for WP10).
- **Scoring:** cosine similarity (normalise vectors, dot product) in numpy (already present via
  rank-bm25); ties by path, so ordering is deterministic.
- **Fill:** BM25's `select_within_budget` (first-fit whole files, `DEFAULT_TOKEN_BUDGET` and
  `_estimate_tokens` from the assembler), then the same rendered-cap drop loop. Dense has no
  "shares no word" zero: the `score <= 0` break only drops negative cosines, which do not occur in
  practice, so **dense fills to the budget**. Consequence to document: on react-shopping-cart the
  whole repo fits, so dense ≈ BM25 ≈ whole repository there; ranking matters only on TakeNote.
- **Cache (committed, the reproducibility mechanism):** `embedding_cache/<project>/text-embedding-3-large.jsonl`,
  one line per text: `{key, kind: "doc"|"query", label, batch: {id, size, prompt_tokens}, created, embedding_b64}`
  (`label` is the file path, or `"<spec>"` for a query),
  where `key = sha256(model + "\0" + text)` and the embedding is float32 base64 (≈16 KB/line,
  ≈2 MB total). Keyed on content, so an edited file misses instead of reusing a stale vector.
  OpenAI embeddings are not bit-reproducible across calls, so **the committed cache is what makes
  runs repeatable**: every candidate of a cell sees identical vectors. Append-only; writes flushed
  per batch.
- **API calls:** only for cache misses, missing docs in batched `litellm.aembedding` calls (64
  inputs per call, so one call per repo here), plus one call for a new query. Tenacity retry on rate-limit/connection errors, same policy
  as `_acompletion_with_retry`.
- **Cost logging (for WP9):** a new `logged_embedding_call()` in `src/llm/logger.py`, reusing
  `_write_log_record` and the record shape (`prompt` holds the embedded paths/`"<spec>"`, not the
  texts; `usage.prompt_tokens` from the response; error records as for completions). New
  `call_purpose` values `embedding_index` and `embedding_query` added to `VALID_CALL_PURPOSES`.
  Cache hits cost nothing and are counted in `retrieval_metadata`. The API reports tokens per
  call, not per input, so each cache line keeps its call's `batch`; WP9 sums `prompt_tokens` over
  distinct batch ids to cost the index from the cache alone, whichever run built it (review F2).
- **Metadata:** as BM25 (`ranked_top` with scores, `included_files`, `skipped_for_budget`,
  `budget_tokens_used`, `token_budget`, `corpus_size`) plus `embedding_model`, `cache_hits`,
  `api_calls`, `api_prompt_tokens`.
- **Missing key:** `pipeline pilot run` exits before any candidate if `text_emb_3_large` is
  selected and `OPENAI_API_KEY` is unset, in `--mock` runs too (review F1). Called directly, the
  retriever raises a clear error only when a cache miss needs the API.

## Files
- **New** `src/retrieval/dense_retriever.py`: `EmbeddingCache` (load/lookup/append JSONL),
  `embed_texts()` (misses → batched call → cache), `rank_by_cosine()`, `DenseRetriever(Retriever)`
  with the same constructor shape as `BM25Retriever` plus `run_id`, `log_dir`, `cache_root`.
- **`src/llm/logger.py`:** `logged_embedding_call()` + two call purposes.
- **`src/generation/orchestrator.py`:** `"text_emb_3_large"` in `KNOWN_CONDITIONS` (not in default
  `CONDITIONS`); dispatch branch next to `bm25` (stays real under `--mock-retrieval`, like
  whole-file and BM25); pass `run_id`/`log_dir`; `retrieval_metadata` already persisted.
- **`conditions/base/text_emb_3_large.toml`:** design comment block and
  `embedding_model = "text-embedding-3-large"`.
- **`conditions/base/nomic_embed_code.toml`:** comment "not run in the IJCKG 2026 leg (WP3 scope)".
- **`.env.example`:** `OPENAI_API_KEY=` line with a note that the dense condition needs it in both
  legs.
- **New** `tests/unit/retrieval/test_dense_retriever.py` (litellm mocked with deterministic
  bag-of-words vectors): cosine ranking puts the matching file first; ties by path; only misses are
  sent, in one batch; second retrieve makes 0 API calls; cache JSONL round-trips float32 exactly;
  changed file content misses; rendered context ≤ budget; metadata populated; a log record with
  `embedding_index`/`embedding_query` and usage is written per API call; missing key with a miss
  raises the clear error, fully cached works without a key.
- **`tests/unit/generation/test_orchestrator.py`:** dispatch test for `text_emb_3_large`
  (mocked), known-but-not-default.

## After the key is set (acceptance + evidence)
**Run procedure.** The cache path `embedding_cache/` is relative to the working directory. When a
run uses an isolated worktree (as the WP5 runs do), the worktree must contain the committed cache,
and **`embedding_cache/` must be copied back to the main tree with the results** — otherwise the
vectors that run used are lost, and later runs re-embed with slightly different vectors (review F6).

1. Dry run on P1, twice: `pipeline pilot run --run claude_primary --tasks P1 --conditions
   text_emb_3_large --mock --n 1 --run-id dense_dryrun_p1[_2]`. First builds the RSC cache
   (`api_calls` > 0), second shows `api_calls = 0`; context ≤ 7000; mock edit → `test_pass`.
2. Warm TakeNote the same way on P3 (`dense_dryrun_p3`).
3. Diagnostic identical to WP2's: rank / in-context of every reference-patch file for P1–P3 and
   draft P4–P6, context tokens, files included; side-by-side with BM25. Queries for P4–P6 drafts
   are cached too (pennies).
4. WP3 note `docs/phase_2/ijckg-2026/wp3_dense.md`: design table, cache/reproducibility, cost,
   diagnostic, the RSC "≈ whole repo" reading, Qwen-leg caveat, Nomic not run.

## Commits (own track, like BM25)
`docs(dense)` plan → `feat(dense)` logger + retriever + wiring → `test(dense)` → `data(dense)`
cache + dry-run artifacts → `docs(dense)` note + revision-plan status. Files staged by explicit path.
Real WP5 dense runs are **not** in this plan.

## Verification
- `uv run pytest tests/unit -q` green (562 + new; 586 after the review fixes).
- BM25 unchanged: `git diff` shows no change to `bm25_retriever.py` or its tests.
- Dry runs: `metadata.json` has `retrieval_token_count ≤ 7000`, populated `retrieval_metadata`,
  second run `api_calls = 0`; `experiment_logs/dense_dryrun_p1/text_emb_3_large.jsonl` has
  `embedding_*` records with usage; harness `test_pass`.

---

## Implementation log (18 Sep)

| Commit | What |
|---|---|
| `97a069a` | `feat(dense)`: `DenseRetriever`, `logged_embedding_call`, orchestrator dispatch, TOMLs, `.env.example` |
| `f646d3f` | `test(dense)`: 19 tests; the concurrency-lock test was mutation-checked (fails with the lock removed) |
| `10e4c25` … `4386735` | review fixes F1–F5, below |
| `be48fcc` | `data(dense)`: caches, `dense_dryrun_p1`/`_p1_2`/`_p3`, `scripts/wp3_recall_diagnostic.py`. Acceptance met; results in [`wp3_dense.md`](wp3_dense.md) |

## Structured review of `ec7e3a9..f646d3f` (18 Sep)

| # | Severity | Finding | Resolution |
|---|---|---|---|
| F1 | Medium | No key and a cold cache turned every dense candidate into a mid-run `harness_error`, spending the run id; the CLI preflight checked only the generator's key | Fixed `10e4c25`: `pilot run` exits before the run (2 tests) |
| F2 | Medium | Rows embedded in a batch stored no token count, contrary to this plan; the index could be costed only from the building run's log | Fixed `038e512`: each row carries its call's `batch` (1 test) |
| F3 | Low | `numpy` imported directly but only locked transitively via `rank-bm25` | Fixed `1afec08`: declared, same locked version |
| F4 | Low | A response with the wrong vector count raised before logging, leaving a billed call unrecorded | Fixed `cfea0c4`: log first, then check (1 test) |
| F5 | Low | Lock registry keyed on `id(loop)`: a later loop could reuse the id and get a lock bound to a dead loop; the registry only grew | Fixed `4386735`: `WeakKeyDictionary` per loop (1 test) |
| F6 | Docs | Cache path is cwd-relative, so a worktree run's cache is lost unless copied back; the cache field is `label`, not `path` | Fixed in this plan: run procedure and cache schema above |

The reviewed BM25 module and its tests are unchanged throughout.
