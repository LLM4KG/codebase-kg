# WP2 — BM25 retriever: design and retrieval diagnostic

> Written 18 Sep 2026. Plan and review log: [`wp2_bm25_plan.md`](wp2_bm25_plan.md). Code:
> `src/retrieval/bm25_retriever.py`; condition: `conditions/base/bm25.toml`.

## What the condition is

A file-level lexical baseline. It differs from KG-augmented **only in how files are chosen**:
same corpus, same budget and estimator, same renderer (Format A), same generator prompt and
output format.

| Choice | Setting | Why |
|---|---|---|
| Corpus | The KG's own file set: `extract_files()` with the project's `exclude_paths` | BM25 sees exactly the files the KG indexed, no more and no fewer |
| Chunk | One per file | Design summary: "file-level chunks" |
| Tokenizer | Non-alphanumeric split plus camelCase split; whole identifier kept; lowercased; small English stoplist; tokens under 2 characters dropped; path included in each document | Matches identifiers in specs (`decreaseProductQuantity`) and path words (`cart-context`) |
| Scorer | `BM25Okapi` term weighting (k1=1.5, b=0.75) with the **Lucene/Elasticsearch IDF** `log(1 + (N−n+0.5)/(n+0.5))` | Standard; no tuning on the tasks. See "Review fixes" |
| Budget | `DEFAULT_TOKEN_BUDGET` = 7,000 via the KG assembler's `_estimate_tokens`, **enforced on the rendered context** | Ground rule 2 |
| Fill | Whole files in rank order, first-fit; files sharing no word with the spec (score 0) excluded | Truncated source would break `search_replace` |

**One departure from the plan** (commit `64857cc`): the plan counted spec + source, which is
the KG assembler's accounting. On TakeNote that rendered at ~7,035 tokens, because each file
also gets a heading and a code fence. The cap is now checked after rendering, dropping the
lowest-ranked file until it holds. So every capped condition's context is ≤ 7,000 estimated
tokens as the model sees it.

## Review fixes (18 Sep)

A structured review of the first implementation (findings F1–F6, listed in
[`wp2_bm25_plan.md`](wp2_bm25_plan.md)) changed three things before any generation run used
BM25:

- **F1, IDF (`b829fba`).** `rank_bm25`'s own IDF floors any word found in more than half the
  files at `0.25 × mean IDF`. On these corpora that floor was *higher* than the IDF of
  moderately common words:
  - TakeNote: `src` (60/60 files) weighed 0.74, against 0.26 for `notes` (26/60);
  - react-shopping-cart: `ts` (34/55) weighed 0.75, against 0.25 for `cart` (24/55).

  Words present in every file therefore outweighed the spec's subject. Ranking also leaned
  towards files with many import paths. Lucene's IDF is positive and strictly decreasing
  (now `src` ≈ 0.008).
- **F3, tokenizer (`d7d83ab`).** One-character tokens are dropped: `product's` gave `s`,
  `$0.00` gave `0`.
- **F2, test (`8eb3a85`).** The rendered-cap test now exercises the drop loop. It was
  mutation-checked: it fails with the loop disabled.

**Still true after the fix:** P2's and P3's statements contain full paths (`src/client/...`),
so every file shares `src` and scores above zero. That word now contributes almost nothing to
ranking. On those tasks the zero-score rule excludes nothing, and the budget does the
limiting.

## Diagnostic: file-level recall within the budget

This measures where each file the reference patch edits ranks, and whether it ended up in the
context. P1–P3 use their frozen statements; P4–P6 use the draft statements in
`wp4_task_drafts.md`. No LLM and no Docker; deterministic.

| Task | Corpus | File the patch edits | BM25 rank | In context | Context tokens | Files in context | Files scoring > 0 |
|---|---|---|---|---|---|---|---|
| P1 | 55 | `useCartProducts.ts` | 2 | yes | 5,634 | 50 | 50 |
| P2 | 60 | `TestID.ts` | 1 | yes | 6,961 | 12 | 60 |
| | | `NoteList.tsx` | 3 | yes | | | |
| | | `note.ts` | 4 | yes | | | |
| P3 | 60 | `NoteMenuBar.tsx` | 1 | yes | 6,962 | 12 | 60 |
| P4 (draft) | 55 | `useCart.ts` | 1 | yes | 4,947 | 37 | 37 |
| | | `Cart.tsx` | 3 | yes | | | |
| | | `useCartProducts.ts` | 5 | yes | | | |
| P5 (draft) | 55 | `CartProduct.tsx` | 1 | yes | 4,600 | 36 | 36 |
| | | `CartProducts.tsx` | 4 | yes | | | |
| P6 (draft) | 60 | `CategoryList.tsx` | 3 | yes | 6,897 | 15 | 42 |

This was re-run after the review fixes; before them P1 ranked its file 3rd and included
53 files.

**Recall within the budget is 11/11 files across all six tasks.** Two readings matter for the
paper:

1. **BM25 is a strong baseline here, not a straw man.** Every file each reference patch edits
   ranks in the top 5 and is in the context, **with its full source**. That includes the two
   files the KG context lacks: `note.ts`'s `noteSlice.actions` export for P2, and
   `useCartProducts.ts` for P4. On these tasks BM25 has at least the information whole-file
   has. Any KG advantage must therefore come from structure and signal-to-noise, not from
   reaching files BM25 cannot.
2. **On react-shopping-cart, BM25 is close to "the whole repository".** The repo's source fits
   inside the budget, and most files genuinely share a word with a cart spec (`cart`,
   `product`), even under Lucene IDF. So P1 includes 50 of 55 files, and P4 and P5 about 37. On TakeNote the budget binds at about
   12 files. Report the context-token and file counts next to BM25's pass rates, so reviewers
   see what each condition was given. The same point applies to the dense retriever (WP3),
   which uses the same fill.
