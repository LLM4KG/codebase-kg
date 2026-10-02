# WP3 — Dense retriever: design and retrieval diagnostic

> Written 18 Sep 2026. Plan, implementation log and review: [`wp3_dense_plan.md`](wp3_dense_plan.md).
> Code: `src/retrieval/dense_retriever.py`; condition: `conditions/base/text_emb_3_large.toml`.
> Diagnostic: `scripts/wp3_recall_diagnostic.py`.

## What the condition is

A file-level embedding baseline. It differs from BM25 **only in how files are scored**, and so
from KG-augmented only in how files are chosen. Corpus, chunks, fill rule, budget, estimator,
renderer (Format A), generator prompt and output format are shared.

| Choice | Setting | Why |
|---|---|---|
| Corpus and chunk | BM25's: the KG's own file set (`extract_files()` with the project's `exclude_paths`), one chunk per file | BM25 and dense see the same units |
| Text embedded | `"<path>\n<source>"` per file; the task statement verbatim as the query | BM25 indexes the path too |
| Model | OpenAI `text-embedding-3-large`, full 3,072 dimensions | Design summary. Every file is under 4k tokens, inside the 8,191-token input limit, so no file is split |
| Scorer | Cosine similarity; ties by path | Standard; deterministic |
| Budget and fill | BM25's first-fit whole files within `DEFAULT_TOKEN_BUDGET` = 7,000 on the KG assembler's `_estimate_tokens`, enforced on the rendered context | Ground rule 2 |
| Zero cut | None in practice: cosines are all positive, so **dense fills the budget** | BM25 stops at files sharing no word with the statement; dense has no such zero |
| Embedder across legs | The same OpenAI model for the Claude and Qwen legs | The retriever is the variable under test. The Qwen leg is therefore not embedding-model-pure |

## Reproducibility: the committed cache

OpenAI embeddings are not bit-reproducible from call to call. The vectors are therefore stored in
`embedding_cache/<project>/text-embedding-3-large.jsonl`, committed, one line per text:
- keyed on a hash of model and text, so an edited file misses rather than reusing a stale vector;
- stored as float32, and used as float32 even on the run that fills the cache, so the run that
  builds it ranks exactly as every later run.

Every candidate of a cell sees identical vectors. A lock per cache file makes candidates that run
at the same time share one API call per text.

Checked by the acceptance dry runs (mock generator, reference edit, Docker harness):

| Run | API calls | Cache hits | Context tokens | Files | Harness |
|---|---|---|---|---|---|
| `dense_dryrun_p1` | 2 (index 11,404 tokens; statement 77) | 0 | 5,905 | 55 / 55 | `test_pass` |
| `dense_dryrun_p1_2` | **0** | 56 | 5,905, identical context | 55 / 55 | `test_pass` |
| `dense_dryrun_p3` | 2 (index + statement, 34,490 tokens) | 0 | 6,919 | 15 / 60 | `test_pass` |

The diagnostic below also ran twice; the second run made no API calls and gave the same table.

## Cost (for WP9)

Each cache row records the API call that produced it (batch id, size, tokens), so the cost comes
from the committed cache alone:

| Repo | Files | Index tokens | Statements embedded | Total tokens |
|---|---|---|---|---|
| react-shopping-cart | 55 | 11,404 | 4 | 11,699 |
| TakeNote | 60 | 34,383 | 4 | 34,772 |
| **Total** | | | | **46,471 ≈ $0.006** at $0.13 / M |

Retrieval-side cost per candidate after the index exists is zero: every candidate of a cell
reuses the statement's vector. Every API call is also in `experiment_logs/<run>/text_emb_3_large.jsonl`
(`call_purpose` `embedding_index` / `embedding_query`).

## Diagnostic: file-level recall within the budget, dense vs BM25

Same method as WP2: rank of every file the reference patch edits, and whether it is in the
context. P1–P3 use their frozen statements; P4–P6 the draft statements in `wp4_task_drafts.md`.
Deterministic; no LLM and no Docker.

| Task | File the patch edits | Dense rank | In context | BM25 rank | In context | Dense tokens / files | BM25 tokens / files |
|---|---|---|---|---|---|---|---|
| P1 | `useCartProducts.ts` | 1 | yes | 2 | yes | 5,904 / 55 | 5,634 / 50 |
| P2 | `note.ts` | 1 | yes | 4 | yes | 6,936 / 13 | 6,961 / 12 |
| | `NoteList.tsx` | 2 | yes | 3 | yes | | |
| | `TestID.ts` | **35** | **no** | 1 | yes | | |
| P3 | `NoteMenuBar.tsx` | 1 | yes | 1 | yes | 6,971 / 16 | 6,962 / 12 |
| P4 (draft) | `Cart.tsx` | 1 | yes | 3 | yes | 5,904 / 55 | 4,947 / 37 |
| | `useCart.ts` | 3 | yes | 1 | yes | | |
| | `useCartProducts.ts` | 2 | yes | 5 | yes | | |
| P5 (draft) | `CartProduct.tsx` | 2 | yes | 1 | yes | 5,904 / 55 | 4,600 / 36 |
| | `CartProducts.tsx` | 4 | yes | 4 | yes | | |
| P6 (draft) | `CategoryList.tsx` | 1 | yes | 3 | yes | 6,979 / 17 | 6,897 / 15 |

**Re-run 19 Sep with the runs' exact query text.** The first version passed each statement with
the YAML's trailing newline, but the orchestrator strips it, so its dense ranks came from slightly
different query vectors. The script now loads statements through the orchestrator's
`load_task_spec`, and P4–P6 from their final YAMLs. The re-run made 0 API calls. Every rank and
every in-context result above is unchanged, and so is `TestID.ts` (rank 35, cosine 0.34). The only
difference is P3's dense context: **6,918 tokens / 15 files** (the table's 6,971 / 16 was the
newline query). The generation runs were never affected: each cell used one vector, and P2's
stripped statement was embedded once, in the Claude P1–P3 leg.

**Recall within the budget: dense 10/11, BM25 11/11.** Three readings for the paper:

1. **Both put a patched file at the top.** Dense ranks one first on P1, P2, P3, P4 and P6, and
   second on P5. BM25 ranks one first on P2, P3, P4 and P5, and second on P1. Top rank does not
   separate the two here. What does is whether *every* patched file is in the context, and how
   much else is.
2. **Dense misses the one purely lexical file.** P2's reference patch adds a constant to
   `TestID.ts`. The statement names test-id identifiers, which BM25 matches exactly (rank 1).
   Dense places the file 35th of 60 (cosine 0.34, against 0.42 for the last file that fits). This
   is exactly the difference between lexical and semantic matching. P2 × dense candidates can
   still pass only by guessing that file's contents, as the KG condition must for `note.ts`'s
   export.
3. **On react-shopping-cart, dense *is* the whole repository.** With no zero cut, all 55 files
   (5.9k tokens) fit in the budget for P1, P4 and P5, so ranking cannot matter there. Dense and
   whole-file differ on that repo only in that whole-file gives just the patch's files. Ranking
   matters only on TakeNote, where the budget binds at 13–17 files. As for BM25, report context
   tokens and file counts next to pass rates.

## Not run

Nomic Embed Code (`conditions/base/nomic_embed_code.toml`) has no retriever and is not run in this
leg. The leg reports five of the six designed conditions; WP10 must say so.
