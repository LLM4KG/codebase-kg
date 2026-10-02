# WP4 — Plan for drafting the new task descriptions (P4–P6)

> Status: **executed 18 Sep 2026.** Drafts in [`wp4_task_drafts.md`](wp4_task_drafts.md), awaiting approval. See "Outcome" at the end: rendering the KG context changed the retriever. Part of WP4 in [`revision_implementation_plan_18-22Sep.md`](revision_implementation_plan_18-22Sep.md#wp4--add-23-pilot-tasks-on-the-existing-docker-repos-19-sep).

## Context
WP4 of `docs/phase_2/ijckg-2026/revision_implementation_plan_18-22Sep.md` adds tasks to the
pilot so the IJCKG revision rests on more than 3 tasks. Every new-task run in WP5 waits on
Anjana approving the task descriptions, so today's deliverable is the **drafts for review**.
Reference patches, tests, Docker validation and timeout calibration follow on 19 Sep, after
approval.

Decisions already made:
- **Three tasks:** P4 feature (react-shopping-cart), P5 refactor (react-shopping-cart), P6 bug fix
  (TakeNote). P1–P6 then have 2 tasks of each type and 3 per repo. Two of the three run on the
  ~10 s react-shopping-cart tests, which keeps WP5 wall-clock time down.
- **Path policy: follow P1 and withhold paths.** Statements name the component, hook or bare
  filename, never the directory path. This settles the open item from gate review v2 §5.1
  ("decide deliberately whether task statements name target paths"). Localisation is then tested
  on 4 tasks (P1, P4–P6), with P2 and P3 as the paths-given contrast.
- **No Redux in solutions** (gate review v2 §6.1). P6's test builds a Redux store, but the fix is
  component-local string logic.

Each candidate was checked against the pinned source (react-shopping-cart `9fa5624`, TakeNote
`e0eddbb`) and against the committed KG in `graph_export/`.

## The three drafts

### P4 — react-shopping-cart, feature addition: "Clear cart"
- **Statement (draft):** "The cart has no way to remove every product at once. Add a `clearCart`
  function to the `useCart` hook that empties the cart and resets its totals. Then add a 'Clear
  cart' button to the `Cart` component's footer that calls it."
- **Anchors:** `Cart` (plus the `useCart` hook).
- **Files the reference patch will change:**
  - `src/contexts/cart-context/useCartProducts.ts`
  - `src/contexts/cart-context/useCart.ts`
  - `src/components/Cart/Cart.tsx`
- **Test:** a `renderHook(useCart)` test with the real `CartProvider`, following the P1 pattern:
  - add products, call `clearCart`, then expect `products` to be `[]` and
    `total.productQuantity` and `total.totalPrice` to be 0;
  - clearing an already-empty cart is a no-op.
  - Unpatched code fails because `clearCart` is undefined.
  - The test checks the logic only, not the button (same choice as P2), and records that.
- **KG coverage:** these edges exist in the committed KG: `Cart -USES_CUSTOM_HOOK-> useCart` and
  `useCart -> useCartProducts / useCartTotal / useCartContext`. The context is hook-mediated with
  no Redux, the positive counterpart to P2. *(Superseded. The edges exist, but the rendered
  context showed the feature-addition template did not read `useCart.ts`. See "Outcome".)*

### P5 — react-shopping-cart, refactoring: make CartProduct presentational
- **Statement (draft):** "`CartProduct` calls `useCart` itself to remove products and change
  quantities. Refactor it into a presentational component that takes `onRemove`, `onIncrease` and
  `onDecrease` callback props (each called with the product). Move the `useCart` call into its
  parent, `CartProducts`, which should pass the callbacks down. Behaviour must not change."
- **Anchors:** `CartProduct`.
- **Files:** `CartProduct.tsx` and `CartProducts.tsx`.
- **Test:**
  - render `CartProduct` without a `CartProvider`, using mock callbacks; clicking remove, `+` and
    `-` calls the right callback with the product;
  - render `CartProducts` inside a `CartProvider` and check it still renders and wires up.
  - Unpatched code fails: `useCart` throws outside the provider, or the callbacks are never called.
    This needs confirming on 19 Sep.
- **Why this task:** unlike P3, it **changes a prop interface**, so it tests the refactoring
  template's caller warning. The KG has the needed edges: `CartProducts -USES_COMPONENT->
  CartProduct` and `PASSES_PROP product`.
- **Rejected alternative:** a `Checkbox` prop rename. Its only caller, `Filter`, uses it through
  a styled wrapper (`styled(CB)`), and the KG has no edge for that. That is the known
  styled-wrapper gap, and it is noted for WP4b instead.

### P6 — TakeNote, bug fix: duplicate category names differing only in case
- **Statement (draft):** "Category names are meant to be unique, but `CategoryList` only rejects a
  duplicate when the case matches exactly: with 'Work' already present, 'work' or 'WORK' can still
  be created or renamed to. Make the duplicate check case-insensitive for both adding and renaming
  a category."
- **Anchors:** `CategoryList`.
- **Files:** `src/client/containers/CategoryList.tsx`, both `onSubmitNewCategory` and
  `onSubmitUpdateCategory`.
- **Test:**
  - Build a store from `rootReducer`, dispatch `addCategory({name: 'Work'})`, then render
    `CategoryList` inside `Provider`, `TempStateProvider` and `DragDropContext`.
  - Click `ADD_CATEGORY_BUTTON`, type `work` into `NEW_CATEGORY_INPUT` and submit. Expect still 1
    category. Then submit `Personal` and expect 2.
  - Unpatched code fails the first assertion.
  - Feasibility risk: the rendering setup is heavier than P2 and P3. If it proves brittle on
    19 Sep, fall back to the add path only.
- **KG coverage:** `CategoryList` and its state variables are in the KG. The duplicate-check logic
  sits inside `onSubmitNewCategory` and `onSubmitUpdateCategory`. *(Corrected: the KG has **no**
  `HAS_HANDLER` edges for them, because they are passed to child components as props, not bound to
  DOM events. So the KG does not model them at all.)* This is useful WP4b evidence either way.

## Output (today, after this plan is approved)
1. **`docs/phase_2/ijckg-2026/wp4_task_drafts.md`:** the review document for Anjana, one section
   per task. Each section gives:
   - the statement, type, repo and pinned commit, anchors and files to change;
   - a test sketch: what it asserts, how the unpatched code fails, and which alternative
     solutions still pass;
   - KG coverage with the edges cited, plus a WP4b note (which entities are representable);
   - "names path: no" (and whether a bare filename appears).

   It ends with an approval checklist and the rough WP5 volume: 150 new candidates, with the
   react-shopping-cart tasks near P1's ~10 s timeout.
2. **`docs/decision-log.md`:** a new top entry, "Task statements withhold target paths (P1
   policy) for P4 onward". It cites gate review v2 §5.1 and records that P2 and P3 stay as they
   are, as the contrast set.
3. **The revision plan:** mark WP4's "Draft the descriptions on 18 Sep" as done, pointing to the
   drafts doc. Replace the line "Record for each task whether its description names the target
   file, as P1's does not" with the adopted policy.

No task YAMLs, patches or tests are written today. `tasks/pilot/P4–P6.yaml` are created on
19 Sep from the approved text, together with their patches and tests. The run task lists
(`RUN_TASKS` in `src/generation/orchestrator.py`) and the calibrate defaults are fixed lists,
so a new YAML is inert until it is added to them.

## Verification
- Check every identifier each statement names against the pinned source with `grep`:
  `clearCart` must be absent, and `useCart`, `CartProduct`, `CartProducts`, `CategoryList`,
  `onSubmitNewCategory` and `onSubmitUpdateCategory` must be present.
- Confirm no statement contains a directory path: grep the drafts doc's statement blocks for `/`.
- Re-run the KG edge check behind each "KG coverage" line against
  `graph_export/{react-shopping-cart,takenote}/full_dump.cypherl`.
- Do not commit until Anjana has reviewed the drafts.

## Outcome (18 Sep)

Everything in "Output" was done: the drafts doc, the path-policy decision-log entry and the
revision-plan update. The work then went further than planned.

1. **State-management check.** The pilot's state-management failure (P2, gate review v2 §6.1)
   was an edited file whose source retrieval never read: the Redux slice. Checking P4–P6 for the
   same pattern meant checking the templates, not only the schema. The assembler read only the
   anchor's source for feature addition. It read custom-hook source for bug fix and refactoring,
   and callers only as metadata for refactoring.
2. **Evidence.** We loaded react-shopping-cart into the scratch Memgraph (7688) and rendered the
   actual KG context for P4 and P5 with their expected anchors, with no classifier call.
   - **P4:** only `Cart.tsx`. `useCart.ts` had no path and no source; `useCartProducts.ts` was
     absent.
   - **P5:** `CartProducts.tsx` source is included only if the classifier also anchors
     `CartProducts`.
3. **Naming paths would not help.** In the pilot, floor failed P2 and P3 20/20 with
   `search_not_found` even though both statements named their paths. Under `search_replace` the
   bottleneck is source text, not localisation, so the P1 path policy stands.
4. **Decision (Anjana).** Widen feature addition to read one-hop custom-hook source, as
   refactoring does, and re-run P2 so all tasks share one retriever.
   - Implemented in `_build_feature_addition` (`src/retrieval/assembler.py`), with a new
     truncation rung (`cypher_templates.md` §8).
   - Added the `pilot run --tasks` option and 5 new unit tests; 543 tests pass.
   - After the change: P4 includes `useCart.ts` (~371 tokens), but still not
     `useCartProducts.ts` (two hops). P2 adds `hooks.ts` (1,235 → ~1,532 tokens) and is
     expected to stay at `build_fail`.
   - Recorded in `docs/decision-log.md` (2026-09-18, "Feature-addition retrieval now reads
     one-hop custom-hook source"). The before/after tables are in the drafts doc.
5. **Still open.** The P2 re-run, planned as its own task below. It must finish before any WP5
   run.

## Follow-up task — P2 re-run under the widened retriever

> Status: **run 18 Sep 2026** at commit `24796cc`: `claude_primary_2026-09-18_p2_hooksrc` and
> `qwen_robustness_2026-09-18_p2_hooksrc`. Acceptance met: 10/10 classified, 0 harness errors, v2
> directories unchanged. **The Claude expectation did not hold:** `test_pass` ×4, `build_fail` ×1,
> against the predicted `build_fail` ×5. Qwen was unchanged (`diff_apply_fail` ×5). The difference
> is a single guessed export edit that the added context says nothing about. Full result and how it
> may be read: `docs/decision-log.md` (2026-09-18 feature-addition entry, "Result").
>
> **Same-day control, run 18 Sep** (`claude_primary_2026-09-18_p2_oldasm_control`, current `HEAD`
> with only the old `assembler.py`, byte-identical v2 context): `test_pass` ×1, `build_fail` ×3,
> `diff_apply_fail` ×1. The export edit was made in 2/5, against 0/5 in July. So **the July result
> does not reproduce on an identical prompt**, and the widening's effect (4/5 vs 1/5 passes,
> p ≈ 0.21) is not distinguishable at n=5. Open for decision: whether WP5 can still reuse the July
> P1–P3 results (see the decision log).

### Why
The published P2 `kg_augmented` results (gate review v2) were produced by the old feature-addition
assembler. After the widening, P2's KG context is different: `NoteList → useKey` adds
`src/client/utils/hooks.ts`. Without a re-run, P2 and P4–P6 would be measured by two versions of
the same retriever. P1 (`bug_fix`) and P3 (`refactoring`) take other code paths, and floor and
whole-file don't use the assembler, so none of them is re-run.

### Scope
P2 × `kg_augmented` × {Claude Sonnet 4.6, Qwen3-Coder} × n=5 = **10 candidates**. That is 10
classifier calls plus 10 generator calls, about $0.1–0.3 in total. Output format is
`search_replace` from the run configs, and everything else is unchanged from v2.

### Pre-registered expectation (written before the run)
| Signal | v2 (old assembler) | Expected after widening |
|---|---|---|
| classifier anchors | `["NoteList"]` in 10/10 | unchanged |
| `retrieval_token_count` | 1,235 | ≈1,532 (+`hooks.ts`, ~290 tok) |
| `hooks.ts` source in `prompt.txt` | absent | present |
| `noteSlice.actions` in `prompt.txt` | absent | still absent |
| Claude stage | `build_fail` ×5 (`TS2614`: no exported member `restoreAllTrash`) | `build_fail` ×5, same error |
| Qwen stage | `diff_apply_fail` ×5 | not predicted: Qwen varies between replicates at temperature 0 (v2 §5.3) |

The added hooks are irrelevant to P2, so the change should be neutral. The re-run checks that it
does no harm; it is not expected to rescue P2. Any move is reported as it is, including a move
down.

### Prerequisites
- The scratch Memgraph `kg-scratch` is running on 7688. It currently holds TakeNote; the loader
  would re-import it if not. Using 7688 leaves the main DB on 7687 untouched.
- The TakeNote harness image `codebase-kg-harness/takenote:pilot` exists.
- `ANTHROPIC_API_KEY` and `OPENROUTER_API_KEY` are in `.env` (checked by the CLI preflight).
- The retriever change is **committed first**, so the run can be tied to a commit SHA.

### Steps
1. Commit the retriever change, tests and docs.
2. Run both legs, each under a new run ID, so the v2 directories are never touched (ground rule 1):
   ```bash
   PIPELINE_DB__URI=bolt://localhost:7688 uv run pipeline pilot run --run claude_primary \
     --tasks P2 --conditions kg_augmented --run-id claude_primary_2026-09-18_p2_hooksrc
   PIPELINE_DB__URI=bolt://localhost:7688 uv run pipeline pilot run --run qwen_robustness \
     --tasks P2 --conditions kg_augmented --run-id qwen_robustness_2026-09-18_p2_hooksrc
   ```
3. Check each candidate against the table above:
   - `candidate_artifacts/<run>/P2__kg_augmented__n*/metadata.json`: `stage`, `apply_mode`,
     `apply_reason`, `retrieval_token_count`;
   - `prompt.txt`: `hooks.ts` present, `noteSlice.actions` absent;
   - `harness_output.json`: the build error (`TS2614` or otherwise);
   - `experiment_logs/<run>/kg_augmented.jsonl`: the classifier anchors;
   - summary: `python3 scripts/gate_review_stats.py <run>`.
4. Compare with v2 per model: the stage distribution, distinct patches (SHA-256 of `diff.patch`),
   and whether any quarantined `apply_mode` appears. Quarantined candidates are never passes.

### Recording
- **Decision log** (the 2026-09-18 feature-addition entry): add a "Result" paragraph with the
  stage matrix, the token counts and whether the expectation held.
- **This file:** mark this task done, with the run IDs.
- **Revision plan (WP4 / WP5):** P2's KG row in the results summary uses the new run IDs from
  now on. v2 stays cited as the pre-change measurement.
- Commit the new `harness_results/`, `candidate_artifacts/` and `experiment_logs/` directories
  with the notes.

### Acceptance
- 10/10 candidates are stage-classified, with 0 harness errors.
- Every expectation row has been checked. Any deviation is explained in the decision log, not
  fixed silently.
- The v2 directories are unchanged: `git status` shows no changes under
  `*_2026-07-30_reeval/`.
