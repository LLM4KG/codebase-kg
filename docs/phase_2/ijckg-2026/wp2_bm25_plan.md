# WP2 — BM25 retriever plan, alongside the same-window P1–P3 re-run (option a)

> Status: **executed 18 Sep 2026.** Part 1 done (`b2f16b8`); Part 2 committed and awaiting Anjana's review (see the BM25 change log). Covers WP2 and the WP5 P1–P3 re-run (option a) in [`revision_implementation_plan_18-22Sep.md`](revision_implementation_plan_18-22Sep.md).

## Context
WP2 of `docs/phase_2/ijckg-2026/revision_implementation_plan_18-22Sep.md` adds a sparse-retrieval
baseline, which reviewers R1 and R2 asked for. `conditions/base/bm25.toml` already exists
("file-level chunks, rank_bm25 library"), and the design summary fixes the method: "file-level
chunks scored against the spec, top-k filling the budget". No retriever class exists yet, and
`rank_bm25` is not a dependency.

At the same time, Anjana chose **option (a)**: re-run all three existing conditions (floor,
whole-file, KG-augmented) on P1–P3 in the WP5 window. The reason is that the same-day control
showed July results do not reproduce on an identical prompt (decision log, 2026-09-18). The
estimate is ≈ $0.85 and ≈ 40 minutes.

Both are to run in the background once Auto mode is on. The one hard constraint is that **the
re-run must not see any BM25 edits**. Conditions TOML and Jinja templates are read from disk for
each candidate, so editing the main tree during a run could leak into it.

---

## Part 1 — Same-window re-run of P1–P3 (start first, runs about 40 min)

1. **Record the decision first.**
   - `docs/decision-log.md`: add a line under the 2026-09-18 feature-addition entry saying
     option (a) was chosen, with the cost estimate.
   - Revision plan: change the WP5 "⚠ Reuse under review" bullet to "decided: (a), re-run all
     conditions". WP5 volume becomes 60 + 90 + 150.
   - Commit.
2. **Isolate the run.** Create a worktree of that commit in the scratchpad
   (`git worktree add --detach <scratch>/wt_rerun HEAD`) and copy `.env` into it. The worktree
   uses the widened assembler (`24796cc`), so every KG cell uses one retriever version.
3. **Run the two legs one after the other**, never alongside each other or a Docker dry run. The
   timeouts were calibrated with at most two candidates running at once. Use the scratch
   Memgraph on 7688, so the main DB is untouched and the loader swaps react-shopping-cart and
   TakeNote as it needs.
   ```bash
   PIPELINE_DB__URI=bolt://localhost:7688 uv run pipeline pilot run --run claude_primary \
     --run-id claude_primary_2026-09-18_wp5_p1p3
   PIPELINE_DB__URI=bolt://localhost:7688 uv run pipeline pilot run --run qwen_robustness \
     --run-id qwen_robustness_2026-09-18_wp5_p1p3
   ```
   The defaults give all three conditions × P1–P3 × n=5, so each leg is 45 candidates.
4. **Bring the results back.**
   - Copy `candidate_artifacts/`, `experiment_logs/` and `harness_results/` for both run IDs into
     the main tree (the results index is per run, so a copy is complete), then remove the
     worktree.
   - Summarise with `python3 scripts/gate_review_stats.py <run>`: the stage matrix, `apply_reason`,
     quarantined modes, and distinct patches per cell.
   - Compare with v2 (July) per cell.
   - Record the results in the revision plan's WP5 section and commit.

---

## Part 2 — BM25 retriever (in the main tree, while Part 1 runs)

### Design decisions (documented in the module docstring and in the WP2 note)
- **Corpus.** The KG's own file set: `extract_files(repo_root, exclude_paths)` from
  `src/extraction/programmatic.py`, with the project's `exclude_paths` from `pipeline.toml`
  (`get_settings().projects[...]`). Same files, same filters, so the baseline cannot see a file
  the KG could not. One chunk per file.
- **Tokenizer (shared by query and documents).**
  - Split on anything that isn't a letter or digit, then split camelCase and PascalCase
    (`decreaseProductQuantity` → `decrease product quantity`) and lowercase everything.
  - Keep each whole identifier as well as its parts, so an exact symbol match scores higher.
  - Include the file's path in its document, since path words are real signal (`cart-context`).
  - Drop a small list of English stopwords from both query and documents.
  - Spec identifiers in backticks count like any other words.
- **Ranking.** `rank_bm25.BM25Okapi` with library defaults (k1=1.5, b=0.75). Scores are sorted
  descending, with ties broken by path so the output is deterministic.
- **Budget fill.** The KG's **exact** budget and estimator: import `DEFAULT_TOKEN_BUDGET` (7000)
  and `_estimate_tokens` from `src/retrieval/assembler.py`, per ground rule 2. The used budget is
  `_estimate_tokens(spec)` plus each included file's source, which is how the KG assembler counts.
  - Files are taken **whole** in rank order. Truncated source would break `search_replace`
    matching.
  - A file that would overflow the budget is **skipped, and filling continues** (first-fit), so
    one large file cannot starve the context. Skipped files are recorded.
  - Files with a score of zero are never included.
- **Rendering.** Format A through `ContextRenderer`, exactly like `WholeFileRetriever`: one
  `ComponentContext(component_type="file")` per included file, and `task_type` from the task YAML
  (the same source whole-file uses). `retriever_name="bm25"`. No LLM call and no KG query, so
  retrieval-side LLM cost is zero, as the design summary requires.
- **Metadata** (`RetrievalResult.metadata`): the query tokens, the top 20 ranked files with
  scores, the included files, the skipped-for-budget files and the estimated tokens.
  - It includes one `RoundRecord`, with the spec as the query and the retrieved files.
  - It is persisted as an additive `retrieval_metadata` field in each candidate's
    `metadata.json`. Today no retriever's metadata is written, and without this BM25's ranking
    would be lost. This is an additive field only; existing fields are unchanged.

### Files
- **New** `src/retrieval/bm25_retriever.py`: `BM25Retriever(Retriever)`, constructed with
  `task_id`, `task_type` and `project_name`, mirroring `WholeFileRetriever`. It contains the
  helpers `tokenize()`, `build_corpus(repo_root, exclude_paths)` and
  `select_within_budget(ranked, spec, budget)`.
- **`src/generation/orchestrator.py`:**
  - add a `cand.condition == "bm25"` branch in `run_one_candidate()`;
  - add `"bm25"` to `KNOWN_CONDITIONS`, but **not** to the default `CONDITIONS`, so existing
    runs are unchanged;
  - write `retrieval_metadata`;
  - update the module docstring's retriever list.
- **`pyproject.toml` / `uv.lock`:** `uv add rank-bm25`.
- **`conditions/base/bm25.toml`:** comment block documenting the corpus, tokenizer, budget and
  fill rule, as `whole_file.toml` does.
- **New** `tests/unit/retrieval/test_bm25_retriever.py`, covering:
  - the tokenizer (camelCase split, whole identifier kept, stopwords, path words);
  - ranking picks the file containing the spec's identifiers;
  - ties are ordered by path;
  - the fill never exceeds 7000 on the shared estimator;
  - an oversize top file is skipped and filling continues;
  - zero-score files are excluded;
  - the rendered context contains paths and source;
  - the metadata is populated;
  - `exclude_paths` is honoured.
- **`tests/unit/generation/test_orchestrator.py`:** `--conditions bm25` is accepted, and
  `run_one_candidate` dispatches to `BM25Retriever` (mocked generator and harness, following the
  existing test pattern).

### Diagnostic for the paper (no Docker, no LLM)
A scratchpad script runs `BM25Retriever` on P1–P3 and on the three draft statements P4–P6. For
each it reports:
- the rank of every file in the reference patch (`files_modified`);
- whether each was included within the budget;
- context tokens.

This is file-level recall@budget, directly comparable to the KG's localisation story. It goes in
a short WP2 note, `docs/phase_2/ijckg-2026/wp2_bm25.md`, with the design decisions above. P4–P6
use their draft paths from `wp4_task_drafts.md` until their YAMLs exist.

### WP2 acceptance, from the revision plan
- Unit tests pass, and the full unit suite stays green.
- **Dry run on P1**, only after Part 1 has finished, so Docker isn't contended:
  `pipeline pilot run --run claude_primary --tasks P1 --conditions bm25 --mock -n 1 --run-id
  bm25_dryrun_p1`. The mock generator emits the reference edit, and the context block must be at
  or under 7000 estimated tokens. This makes no API calls.
- Commit the code, tests, `uv.lock`, WP2 note and dry-run artifacts, following the commit rules below.

**Not in this plan:** the real BM25 generation runs (WP5). They start only after P4–P6 are
approved and validated, so all BM25 cells share one window with the other conditions.

---

## Keeping the two tracks separate (for review)

Everything goes on `4-phase2-1a-implementation-ijckg-2026` (ground rule: no other branch). The
BM25 work must be reviewable on its own, so the two tracks never share a commit.

**Commit rules**
- **Stage by explicit path, never `git add -A` or `git add .`.** The re-run writes run directories
  into the main tree while BM25 is being edited, so a broad `add` would mix the two.
- **Prefixes identify the track:**
  - Part 1, the re-run: `data(wp5): …` for run data and `docs(wp5): …` for its notes. Only
    `candidate_artifacts/`, `experiment_logs/`, `harness_results/` for the two `*_wp5_p1p3` run
    IDs, plus the WP5 lines in the revision plan and decision log.
  - Part 2, BM25: `feat(bm25): …`, `test(bm25): …` and `docs(bm25): …`. Only the files listed
    under Part 2, plus `wp2_bm25.md` and the `bm25_dryrun_p1` artifacts.
- **BM25 is split into small, reviewable commits**, in this order:
  1. dependency (`rank-bm25`, `uv.lock`);
  2. retriever and its unit tests;
  3. orchestrator dispatch, `retrieval_metadata` and their tests;
  4. `bm25.toml` comments and the WP2 note with the diagnostic;
  5. dry-run artifacts.
- **Nothing BM25-related is committed until the unit suite passes.** The code is not merged into
  any run until Anjana has reviewed it.

**Logs kept in this file**, each filled in as its commits land:

### Re-run log (Part 1)
| Commit | What | Run IDs / files |
|---|---|---|
| `e8a10ce` | decision record; the worktree was created from this commit | — |
| `b2f16b8` | results, both legs (90/90 classified, 0 harness errors, 0 quarantined, ~$0.84) | `claude_primary_2026-09-18_wp5_p1p3`, `qwen_robustness_2026-09-18_wp5_p1p3` |

Verified passes, July v2 → 18 Sep (n=5 per cell):

| Model | floor | whole-file | KG-augmented |
|---|---|---|---|
| Claude | 0/15 → 0/15 | 15/15 → 15/15 | 10/15 → **15/15** (P2 0/5 → 5/5; P1 and P3 unchanged) |
| Qwen | 0/15 → 0/15 | 11/15 → 10/15 (P2 2 → 1) | 6/15 → 8/15 (P3 1 → 3) |

Claude's P2 KG gain is the same single export edit as in the P2 re-run: 5/5 made it. See the
decision log for how it may be read.

### BM25 change log (Part 2): for review
| Commit | What | Files | Tests | Deviation from plan |
|---|---|---|---|---|
| `5d45375` | 1. dependency: `rank-bm25` 0.2.2 (pulls numpy 2.5.3) | `pyproject.toml`, `uv.lock` | — | none |
| `6088e77` | 2. `BM25Retriever`: corpus, tokenizer, `BM25Okapi`, first-fit fill, metadata | `src/retrieval/bm25_retriever.py` | `test_bm25_retriever.py` (12) | none |
| `cd66ff4` | 3. `bm25` dispatch; `KNOWN_CONDITIONS` (not default); additive `retrieval_metadata` in `metadata.json` | `src/generation/orchestrator.py` | `test_orchestrator.py` (+3) | `retrieval_metadata` is written for **every** retriever ({} for floor), so KG anchors are now persisted too, which was needed anyway |
| `64857cc` | 2b. cap enforced on the **rendered** context | `src/retrieval/bm25_retriever.py` | +1 | **yes:** the plan counted spec + source; TakeNote rendered at ~7,035. Now drops the lowest-ranked file until rendered ≤ 7,000 |
| `c1f690a` | 4. `bm25.toml` comments; WP2 note with recall diagnostic (11/11 files in context on P1–P6) | `conditions/base/bm25.toml`, `wp2_bm25.md` | — | none |
| *(this commit)* | 5. mock dry run on P1 (no API calls): `test_pass` / `exact_unique`, context 5,838 tokens, 53 files, `useCartProducts.ts` ranked 3 | `*/bm25_dryrun_p1/` | — | none. Ran after Part 1 finished, so Docker was uncontended |

**Structured review (18 Sep) and fixes.** Findings from reading the full diff, with each
uncertain point measured on the real corpora:

| # | Severity | Finding | Resolution |
|---|---|---|---|
| F1 | medium–high | `rank_bm25`'s IDF floor weighted ubiquitous words above discriminative ones (`src` 0.74 vs `notes` 0.26); every file scored > 0 | `b829fba`: Lucene IDF subclass (`LuceneBM25`) + 2 tests |
| F2 | medium | the rendered-cap test never reached the drop loop | `8eb3a85`: new test; mutation-checked |
| F3 | low | one-character tokens (`s`, `0`) in queries | `d7d83ab`: dropped + 1 test |
| F4 | low | `wp2_bm25.md` described the IDF behaviour wrongly | this commit: note corrected, diagnostic re-run (11/11 still in context; P1 rank 3 → 2) |
| F5 | low | BM25 gets the YAML task type, as whole-file does; KG gets the classifier's (15/15 correct in the same-window run) | kept and documented, as decided |
| F6 | low | files skipped before the rendered-cap drop are not re-tried | documented in the module docstring (`b829fba`) |

No finding in the orchestrator changes, determinism, corpus cache or dependency pin. Suite: 562
passed.

**Things to look at in review:**
- the tokenizer's stoplist (deliberately small, code keywords kept);
- the first-fit rule;
- the rendered-cap loop (`64857cc`);
- the finding that BM25 is close to the whole repository on react-shopping-cart (`wp2_bm25.md`,
  reading 2).

To review, use `git log --oneline --grep='(bm25)'`, or `git show <sha>` on each row. Every row
also records any deviation from the design decisions above.

## Verification
- `uv run pytest tests/unit -q`: all green, plus the new BM25 and orchestrator tests.
- `git -C <worktree> log -1` equals the recorded commit, and `git status` in the main tree shows
  no changes under any `*_2026-07-30_reeval/` or `*_2026-09-18_p2_*` directory.
- The Part 1 summary shows 90/90 candidates classified with 0 harness errors. Any quarantined
  `apply_mode` is reported separately.
- The BM25 dry-run `metadata.json` has `retrieval_token_count ≤ 7000` and a populated
  `retrieval_metadata`, and the harness stage for the mock reference edit is `test_pass`.
