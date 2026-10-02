# WP4 — New task drafts P4–P6 (for review)

> **Status: approved 19 Sep; built, validated in Docker and calibrated 19 Sep** (see
> "Validation record" at the end). Statements unchanged from the drafts below. Plan:
> [`wp4_task_drafting_plan.md`](wp4_task_drafting_plan.md). Parent: WP4 in
> [`revision_implementation_plan_18-22Sep.md`](revision_implementation_plan_18-22Sep.md).
> Nothing under `tasks/pilot/` is written until you approve. Reference patches, tests, Docker
> validation and calibration are 19 Sep work.
>
> **Retriever changed after drafting (18 Sep):** feature addition now reads one-hop custom-hook
> source (decision log, 2026-09-18). The KG-context tables under P4 and P5 show before and after.
> P2 is re-run under the new code before any WP5 run.

## Summary

| Task | Repo | Type | Anchor | Files the reference patch changes | Statement names a path? |
|---|---|---|---|---|---|
| P1 *(existing)* | react-shopping-cart | bug_fix | `CartProduct` | 1 | bare filename only |
| P2 *(existing)* | takenote | feature_addition | `NoteList` | 3 | full paths |
| P3 *(existing)* | takenote | refactoring | `NoteMenuBar` | 1 (+1 created) | full paths |
| **P4** | react-shopping-cart | feature_addition | `Cart` | 3 | **no** (component and hook names only) |
| **P5** | react-shopping-cart | refactoring | `CartProduct` | 2 | **no** |
| **P6** | takenote | bug_fix | `CategoryList` | 1 | **no** |

With P4–P6 there are 2 tasks of each type and 3 per repo.

**Path policy (adopted for P4 onward):** a statement names components, hooks and functions, and
may name a bare filename, but never a directory path. This follows P1, the pilot's only task where
the KG supplied localisation (gate review v2 §5.1). P2 and P3 keep their full paths and serve as
the "paths given" contrast set. Recorded in `docs/decision-log.md` (2026-09-18).

**No Redux in solutions.** P4 and P5 use React context and hooks only. P6's test builds a Redux
store, but its fix is string logic inside one component.

**WP5 volume:** 5 conditions × 3 tasks × 5 repetitions × 2 models = **150** new candidates, plus
60 for BM25 and dense retrieval on P1–P3, plus the **10**-candidate P2 `kg_augmented` re-run under
the widened retriever (done before WP5). The react-shopping-cart tasks should calibrate near P1's
≈10 s; P6 near P2 and P3 (≈150–175 s).

Pinned commits are unchanged from P1–P3: react-shopping-cart `9fa56244d0f0c0d363cab744a3305c50eabc08cb`,
takenote `e0eddbb9a21ae4cf4c4c7c183f29cfd666e08331`. Each task applies to a clean checkout. P4
and P5 do **not** include P1's fix.

---

## P4 — react-shopping-cart, feature addition: "Clear cart"

### Statement (draft)

> The shopping cart has no way to remove every product at once. Add a `clearCart` function to the
> `useCart` hook that empties the cart and resets its totals, and add a "Clear cart" button to the
> footer of the `Cart` component that calls it.

- **task_type:** `feature_addition`
- **Expected anchors:** `Cart` (the `useCart` hook is also named, and custom-hook anchors resolve
  since the Phase 2.2 fix)
- **Files the reference patch changes:**
  - `src/contexts/cart-context/useCartProducts.ts`: add `clearCart`, which calls `setProducts([])` and `updateCartTotal([])`
  - `src/contexts/cart-context/useCart.ts`: expose `clearCart`
  - `src/components/Cart/Cart.tsx`: add the footer button
- **Where localisation is needed:** the statement never mentions `useCartProducts` or
  `useCartTotal`, where the product list and the totals actually live. A model that adds
  `clearCart` directly in `useCart` (using `useCartContext`) is also valid, and the test allows it.

### Test sketch

File: `src/contexts/cart-context/__tests__/P4_clear_cart.test.tsx` (next to P1's).

The test uses `renderHook(() => useCart(), { wrapper: CartProvider })` with the **real**
provider, not P1's `React.useContext` mock, so it is independent of where `clearCart` is
implemented. It checks:
1. `clearCart` is a function returned by `useCart`.
2. After `addProduct` twice (two different mock products), `clearCart()` leaves `products`
   equal to `[]`.
3. After `clearCart()`, `total.productQuantity === 0`, `total.totalPrice === 0` and
   `total.installments === 0`.
4. Calling `clearCart()` on an empty cart does not throw, and the cart stays empty.

- **Unpatched code fails:** `clearCart` is undefined, so assertion 1 fails and the calls in
  2–4 throw.
- **Valid alternatives that still pass:**
  - implement it in `useCartProducts` or in `useCart`;
  - reset totals via `updateCartTotal([])` or `setTotal(initial)`.
- **Would fail:** clearing products without resetting totals (assertion 3). The statement asks
  for totals to be reset.
- **Not tested:** the button, including its label and position. Same choice as P2, whose test
  covers the reducer only. Record this in the adversarial notes.

### KG coverage (committed `graph_export/react-shopping-cart`)

- `Cart -USES_CUSTOM_HOOK-> useCart`
- `useCart -USES_CUSTOM_HOOK-> useCartProducts, useCartTotal`
- `useCartProducts -USES_CUSTOM_HOOK-> useCartContext, useCartTotal`
- `Cart -HAS_HANDLER-> handleCheckout, handleToggleCart`
- `Cart -USES_COMPONENT-> CartProducts`

At the schema level, this is the context-and-hook counterpart to P2. The feature crosses
component → hook → context the same way P2 crosses component → slice, but every hop is a modelled
entity. Retrieval is a separate question: the table below shows how much of that chain reaches the
prompt.

**WP4b note:** every entity the patch touches is representable. The new function `clearCart` is a
hook return value, which the schema does not model as a node, the same as the existing
`addProduct`.

**What the KG-augmented prompt actually contains** (rendered 18 Sep with anchor `Cart`; see
`docs/decision-log.md`, "Feature-addition retrieval now reads one-hop custom-hook source"):

| Retriever version | Size | `Cart.tsx` | `useCart.ts` | `useCartProducts.ts` |
|---|---|---|---|---|
| before 18 Sep | ~270 tok | source | name only (no path, no source) | absent |
| after the widening | ~371 tok | source | **source** | absent (two hops) |

After the widening, the model sees `useCart`'s full body, including its
`import useCartProducts from './useCartProducts'` and its `useCartContext()` call, but not
the context's `setProducts`/`setTotal`. It can place `clearCart` in `useCart.ts`. Emptying the
cart there still means guessing the context's shape, or delegating to `useCartProducts`
without seeing it. **Pre-registered expectation:** KG-augmented is the hardest non-floor
condition on P4, because the one hop it can't follow is where the state lives.

---

## P5 — react-shopping-cart, refactoring: make `CartProduct` presentational

### Statement (draft)

> `CartProduct` calls `useCart` itself to remove a product and change its quantity. Refactor it
> into a presentational component that receives three callback props, `onRemove`, `onIncrease`
> and `onDecrease`, each called with the product. Move the `useCart` call into its parent,
> `CartProducts`, which should pass the callbacks down. The cart's behaviour must not change.

- **task_type:** `refactoring`
- **Expected anchors:** `CartProduct` (`CartProducts` is also named)
- **Files the reference patch changes:**
  - `src/components/Cart/CartProducts/CartProduct/CartProduct.tsx`: remove `useCart`; accept and call the three props
  - `src/components/Cart/CartProducts/CartProducts.tsx`: call `useCart`; pass the three props
- **Why this task:** unlike P3, it **changes a prop interface**. It therefore exercises the
  refactoring template's caller warning ("Refactoring CartProduct's prop interface will require
  updating 1 caller: CartProducts"). In P3 that warning was informational only.

### Test sketch

File: `src/components/Cart/CartProducts/CartProduct/__tests__/P5_presentational_cart_product.test.tsx`.

It renders with `renderWithThemeProvider` (from `utils/test/test-utils`) and uses a
`mockCartProducts` entry. Its real `sku` is needed by the image `require`.
1. **`CartProduct` without a `CartProvider`**, given three `jest.fn()` callbacks and a product
   with `quantity: 2`:
   - clicking the remove button (`title="remove product from cart"`) calls `onRemove(product)`;
   - clicking `+` calls `onIncrease(product)`;
   - clicking `-` calls `onDecrease(product)`.
2. **`CartProducts` inside `CartProvider`**, given one product, renders it, and clicking its
   `+` does not throw. This checks the parent now supplies the callbacks.

- **Unpatched code fails:** part 1 throws `useCartContext must be used within a CartProvider`,
  confirmed in `CartContextProvider.tsx`.
- **Valid alternatives that still pass:**
  - bind the callbacks inline or through named handlers;
  - pass `product` or look it up by id, as long as the callback receives the product object.
- **Would fail:**
  - renaming the props, since the test passes them by name and the statement names them;
  - keeping `useCart` inside `CartProduct` as a fallback when no props are given (part 1 still
    throws outside the provider).
- **To confirm on 19 Sep:** the `-` button is `disabled` at `quantity === 1`, so the fixture
  must use `quantity: 2`.

### KG coverage

- `CartProducts -USES_COMPONENT-> CartProduct`, `CartProducts -PASSES_PROP(product)-> CartProduct`
- `CartProduct -ACCEPTS_PROP-> product`
- `CartProduct -HAS_HANDLER-> handleRemoveProduct, handleIncreaseProductQuantity, handleDecreaseProductQuantity`
- `CartProduct -USES_CUSTOM_HOOK-> useCart`
- `Cart -USES_COMPONENT-> CartProducts` (the grand-caller, unaffected)

**WP4b note:** fully representable. The caller edge the template relies on exists.

**What the KG-augmented prompt actually contains** (rendered 18 Sep; refactoring is unaffected
by the feature-addition change):

| Classifier anchors | Size | Source included | `CartProducts.tsx` |
|---|---|---|---|
| `CartProduct` | ~361 tok | `CartProduct.tsx`, `useCart.ts` | caller warning and path only, **no source** |
| `CartProduct`, `CartProducts` | ~497 tok | both components + `useCart.ts` | source |

So P5's KG result depends on whether the classifier extracts both names. The statement names both,
so it is likely. The refactoring template never reads a caller's source. That is recorded, not
changed: it is the same boundary P3 already ran under.

**Rejected alternative:** a `Checkbox` prop rename (`handleOnChange` → `onChange`). Its only
caller, `Filter`, renders it through a styled wrapper (`styled(CB)` in `Filter/style.ts`), and
the KG has **no** `Filter → Checkbox` edge. The caller warning would report 0 callers. This is
the known styled-wrapper gap, recorded for WP4b rather than turned into a task.

---

## P6 — TakeNote, bug fix: duplicate category names that differ only in case

### Statement (draft)

> Category names are supposed to be unique, but `CategoryList` only rejects a duplicate when the
> case matches exactly: with a category "Work" already present, the user can still create a new
> category called "work" or "WORK", or rename another category to it. Make the duplicate check
> case-insensitive, both when adding a category and when renaming one.

- **task_type:** `bug_fix`
- **Expected anchors:** `CategoryList`
- **Files the reference patch changes:** `src/client/containers/CategoryList.tsx`. It changes the
  comparison in both `onSubmitNewCategory` and `onSubmitUpdateCategory`, for example
  `cat.name.toLowerCase() === category.name.toLowerCase()`.
- **Not in the fix:** the `category` slice. `addCategory` and `updateCategory` are plain
  reducers, and the check lives in the component. Fixing it in the reducer instead would also make
  the test pass. That is valid, but it needs Redux knowledge, so record which one each candidate
  does.

### Test sketch

File: `tests/unit/client/containers/P6_category_case_insensitive.test.tsx`.

**Setup:**
- Build a store with `configureStore({ reducer: rootReducer })` and dispatch
  `addCategory({ id: '1', name: 'Work', draggedOver: false })`.
- Render `<Provider store><TempStateProvider><DragDropContext onDragEnd={noop}><CategoryList/>…`.
  `CategoryList` uses `Droppable` and `useTempState`, so both wrappers are needed.

**Checks:**
1. Click `ADD_CATEGORY_BUTTON`, type `work` in `NEW_CATEGORY_INPUT`, submit
   `NEW_CATEGORY_FORM`. The store still has 1 category.
2. The same with `  WORK  `, which also checks that trimming still applies. Still 1 category.
3. The same with `Personal`. Now 2 categories. This normal path guards against a fix that
   rejects everything.
4. *(If the rename flow can be driven reliably: dispatch `setCategoryEdit` for a second
   category and submit `work` through its edit form. The name is unchanged.)*

- **Unpatched code fails:** check 1 finds 2 categories.
- **Valid alternatives that still pass:** `toLowerCase` or `localeCompare` with
  `sensitivity: 'base'`, a shared helper, or the reducer-level fix above.
- **Feasibility risk:** this is the heaviest test setup so far. If check 4, or the form
  interaction, is brittle in the node-14 image, drop check 4 and keep the adding path only. The
  statement would then still ask for both, and the test would cover one.

### KG coverage (committed `graph_export/takenote`)

- `AppSidebar -USES_COMPONENT-> CategoryList`
- `CategoryList -USES_COMPONENT-> AddCategoryForm, AddCategoryButton, CategoryOption, CollapseCategoryListButton`, with `PASSES_PROP` to each
- `CategoryList -USES_LIBRARY_HOOK-> useSelector, useDispatch, useState, useRef, useEffect`
- `CategoryList -CONSUMES_CONTEXT-> TempStateContext`, `-USES_CUSTOM_HOOK-> useTempState`
- `CategoryList -DECLARES_STATE-> optionsId, optionsPosition, isCategoryListOpen`

**WP4b note, a genuine gap:** the KG has **no `HAS_HANDLER` edges** for `onSubmitNewCategory` or
`onSubmitUpdateCategory`, the two functions that contain the bug. They are passed as props
(`submitHandler=`, `onSubmitUpdateCategory=`) to child components rather than bound to a DOM
event, and the `props_and_handlers` prompt excludes such handlers by design. So the KG context
names the right component, but not the functions to change. The fix is still within the one file
that retrieval returns. This is the same prop-vs-handler boundary as the 2026-09-18 decision-log
entry, now seen from the task side.

---

## Approval checklist (Anjana)

- [x] P4 statement approved (or edited)
- [X] P5 statement approved (or edited)
- [x] P6 statement approved (or edited). If P6's test proves infeasible on 19 Sep, is the
      adding-path-only fallback acceptable?
- [x] Path policy approved (component, hook or bare-filename level; no directory paths)

## 19 Sep, after approval

**Prerequisite, independent of approval:** the P2 re-run under the widened retriever (`pilot run
--tasks P2 --conditions kg_augmented`, both runs, new `--run-id`s). Record the result in the
decision-log entry before any WP5 run.

For each task, in P4 → P5 → P6 order (cheapest to validate first):
1. Write the test **before** the reference patch (adversarial mode, as in Work item 1).
2. Write `tasks/pilot/P<n>.yaml` in the P1–P3 format, plus `patches/P<n>.diff` and
   `tests/<file>`. Record "statement names path: no" in the YAML comments.
3. Validate in Docker: the unpatched checkout fails the test, and the reference patch passes it.
4. Run `pipeline pilot calibrate --task P<n>`. This writes `conditions/timeouts.toml`, so pass
   every task id to calibrate in one run: `--task P1 --task P2 … --task P6`.
5. Add the task to `RUN_TASKS` in `src/generation/orchestrator.py`. The task list there is
   fixed, not read from the YAMLs, so a new YAML is inert until it is added.

## Validation record (19 Sep)

All three tasks are in `tasks/pilot/` (YAML, `patches/P<n>.diff`, `tests/<file>`), each test
written before its reference patch. Unpatched runs use `scripts/wp4_validate_unpatched.sh P<n>`:
the task's image with the test mounted at the harness path and the project's test command. The
patched side is the calibration run: the reference patch through the full harness, 3 times,
including TakeNote's `npm run build`.

| Task | Unpatched | Failure is the intended one | Reference patch (calibration, 3 runs) | Timeout |
|---|---|---|---|---|
| P4 | 4 of 4 tests fail | `clearCart` is undefined | `test_pass` ×3, `strict` | 13,072 ms |
| P5 | 3 of 5 fail; the 2 behaviour guards pass by design | `useCartContext must be used within a CartProvider` | `test_pass` ×3, `strict` | 12,653 ms |
| P6 | 3 of 5 fail (both "reject" adds and the "reject" rename); both accepting cases pass | the store keeps the case-variant duplicate | `test_pass` ×3, `strict` | 146,329 ms |

- **P6 needs no fallback.** The rename flow (dispatch `setCategoryEdit`, then submit the
  `CATEGORY_EDIT` input's form) is reliable in the node-14 image, so the test covers both
  paths the statement asks for.
- **P5's test is stronger than the sketch.** Part 2 puts a product in a real cart and checks that
  `+`, `-` and remove change the cart through `CartProducts`, not only that clicking does not
  throw.
- **P1–P3 were not recalibrated.** `calibrate` merges into `conditions/timeouts.toml`, so only
  P4–P6 ran. P1–P3 keep the timeouts their WP5 cells already ran under.
- The calibration's P4–P6 results are in `harness_results/calibration/`.
- P4–P6 are in `RUN_TASKS` for both legs.
- WP4b: [`schema_coverage.md`](schema_coverage.md).
