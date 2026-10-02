# WP11 — Redux schema extension: implementation plan

> Written 20 Sep 2026, **for the first implementation leg after the paper is submitted —
> 29 Sep 2026 at the earliest.** Not part of this revision, and not part of the writing leg
> either. The calendar is fixed: implementation ends **22 Sep**, writing runs **23–28 Sep**,
> and §4 of [`revision_implementation_plan_18-22Sep.md`](revision_implementation_plan_18-22Sep.md)
> puts "schema extension for Redux or state management" out of scope. Nothing here changes
> any of that. The document exists so that (a) WP10 and the paper can cite a designed and
> costed plan instead of an intention, and (b) the work can start without a design phase
> whenever the next implementation leg opens.

## Context

[`schema_coverage.md`](schema_coverage.md) names **G1 — Redux state and actions** as one of four
measured schema gaps, and P2 as its documented negative case. This plan closes G1.

### What the graph holds today

Measured on `graph_reruns/takenote/full_dump.cypherl` (the graph of record, 397 nodes):

| Present | Absent |
|---|---|
| `File` nodes for all 5 slices, `slices/index.ts`, `selectors/index.ts`, `sagas/index.ts` | any node for a slice, action, reducer or selector |
| `Library` nodes: `@reduxjs/toolkit`, `react-redux`, `redux`, `redux-saga` | any edge from a component to the state it reads |
| `Library_Hook` `useSelector::react-redux`, `useDispatch::react-redux` | any edge from a component to the action it dispatches |
| **29** `USES_LIBRARY_HOOK` edges into those two hooks | which slice, which action, which field |

So the graph states 29 times that *a component talks to the store* and never *what it says*. The
extractable surface it misses, counted in the repo at the pinned SHA: **5 slices, 50 reducer keys,
5 selectors, 39 distinct `dispatch(...)` call sites**.

### Consequence, measured

`wp5_outcomes.md`, P2 ("add a `restoreAllTrash` reducer action to the note slice, then a Restore
All button in `NoteList`"):

| Condition | Claude Sonnet 4.6 | Qwen3-Coder |
|---|---|---|
| KG-augmented | 5/5 | **0/5** |
| BM25 | 5/5 | 3/5 |
| dense | 5/5 | 4/5 |
| whole-file (oracle) | 5/5 | 1/5 |

P2's KG context is **1,532 tokens** against ~6,960 for both baselines (`wp9_cost.md` §3). The KG
arm is the only condition where the weaker model scores zero, and it is the condition that cannot
see the slice. This is one task on one model and is stated as an observation, not a claim — but it
is the sharpest evidence available that G1 costs something.

### Scope is one repo

Checked `package.json` at each pinned SHA:

| Repo | Redux |
|---|---|
| **takenote** | `@reduxjs/toolkit ^1.4.0`, `react-redux ^7.2.1`, `redux ^4.0.5`, `redux-saga ^1.1.3` |
| react-shopping-cart | none — Context API (`contexts/cart-context`, hence the `base_url` config) |
| SnapShot, jira_clone, todoist | none |

TakeNote holds P2, P3 and P6. react-shopping-cart (P1, P4, P5) is unaffected, so **half the task
set cannot exercise this work** — which bounds what the extension can be claimed to demonstrate
and is the main argument for adding a second Redux repo (see Step 6).

---

## Design

### Answering "is store / slices / actions / reducers enough?"

The nouns are the right starting point, with two corrections and three additions. All of them come
from TakeNote's actual code, not from the Redux documentation.

**Correction 1 — reducers and actions are not separable under RTK.** `createSlice` generates
exactly one action creator per reducer key (`src/client/slices/auth.ts`: `reducers: { login,
loginSuccess, loginError, logout, logoutSuccess }` → `authSlice.actions` with the same five
names). Modelling `Reducer` and `Action` as two node types double-counts one construct. **One
`Redux_Action` node per reducer key**, with the reducer body as its evidence.

**Correction 2 — the store is nearly contentless.** There is one `configureStore` in
`src/client/index.tsx`. Its only retrieval-relevant content is the `combineReducers` map in
`slices/index.ts` (`authState → authReducer`, `noteState → noteReducer`, …), which is what makes
`useSelector(state => state.noteState)` resolvable to a slice. That is an **edge property**, not a
node worth its own label. No `Redux_Store` node.

**Addition 1 — the component↔store edges are the whole point.** Nodes alone reproduce what grep
already finds; BM25 reads the slice file perfectly well. The KG's only possible advantage is
answering *which slice and which action does this component touch*, which is an edge question.
`DISPATCHES` and `READS_SLICE` are the deliverable; the nodes are scaffolding for them.

**Addition 2 — selectors.** `src/client/selectors/index.ts` is the indirection between
`useSelector` and the slice (`getNotes = (state: RootState) => state.noteState`). Without a node
for it, a component's read edge cannot be resolved at all — the argument to `useSelector` is an
imported identifier that resolves to nothing in the current graph.

**Addition 3 — sagas.** TakeNote uses `redux-saga`, not thunks. `sagas/index.ts` imports 20 action
creators across 4 slices and wires them with `takeLatest`/`put`. Async flows
(`loadNotes → saga → loadNotesSuccess`) are invisible without a saga edge, and half the actions in
`note.ts` and `category.ts` exist only to be consumed by one.

**Known entanglement — G3.** To add a reducer you need the state's field list, and TakeNote's
`NoteState` / `CategoryState` live in `@/types`, a non-React module: schema gap **G3**. Closing G1
alone still leaves the state shape unreachable through the graph. The mitigation below
(`stateFields` as a property on `Redux_Slice`, read from `initialState` in the slice file itself)
buys the useful 80% of G3 for this case without opening G3 generally.

### Proposed schema delta

**3 new node types** (11 → 14):

| Label | Key (`uid`) | Properties |
|---|---|---|
| `Redux_Slice` | `name::filePath` | `name` (the `createSlice` `name:`, e.g. `"note"`), `filePath`, `stateKey` (`"noteState"`, from `combineReducers`; empty if unregistered), `stateFields` (list, from `initialState`), `actionCount` |
| `Redux_Action` | `name::sliceName::filePath` | `name`, `sliceName`, `filePath`, `payloadType` (the `PayloadAction<T>` argument, `"none"` when the reducer takes only `state`), `mutatesFields` (list) |
| `Redux_Selector` | `name::filePath` | `name`, `filePath`, `sliceKey` (`"noteState"`), `exportType` |

**6 new relationship types** (30 → 36):

| Edge | Created in | Notes |
|---|---|---|
| `(Redux_Slice)-[:DEFINED_IN]->(File)` | Stage 3 | reuses the existing edge type — not new, listed for completeness |
| `(Redux_Slice)-[:DECLARES_ACTION]->(Redux_Action)` | Stage 3 | within-file, no resolution needed |
| `(Redux_Selector)-[:READS_SLICE]->(Redux_Slice)` | Stage 4 | joins on `sliceKey` ↔ `stateKey` |
| `(FC\|CC)-[:DISPATCHES]->(Redux_Action)` | Stage 4 | **the high-value edge**; `count` property |
| `(FC\|CC)-[:USES_SELECTOR]->(Redux_Selector)` | Stage 4 | `useSelector(getNotes)` |
| `(FC\|CC)-[:READS_SLICE]->(Redux_Slice)` | Stage 4, programmatic | transitive closure of the two above, materialised so `bug_fix.cypher` needs one hop, not two |
| `(File)-[:HANDLES_ACTION]->(Redux_Action)` | Stage 4 | saga side; source is the saga `File`, since the watcher generators are not components or hooks and G2 has no node for them |

`HANDLES_ACTION` hanging off `File` is a deliberate compromise, not an oversight: modelling saga
generators properly means closing **G2** (functions that are neither components nor DOM handlers),
which affects 5 of 6 tasks and is a larger piece of work. Anchoring on the file keeps the async
flow visible at the cost of grain. Revisit when G2 is addressed.

### Explicitly out of scope for WP11

- Thunks / `createAsyncThunk` (`getDefaultMiddleware({ thunk: false })` — TakeNote disables them).
- `extraReducers`, `createEntityAdapter`, RTK Query — none appear in TakeNote.
- Middleware other than the saga registration.
- Context API ↔ Redux unification. react-shopping-cart's `cart-context` is already covered by
  `Context` / `PROVIDES_CONTEXT` / `CONSUMES_CONTEXT`; merging the two state models into one
  abstraction is a research question, not an extraction one.
- MobX, Zustand, Recoil: absent from all five repos.

---

## Extraction

### Step 1 — Two new prompts, both as **new** `prompt_id`s

This is the single most important implementation constraint, and it is settled precedent. From
`3ed4db3` (the `Custom_Hook` addition): the LLM cache key is `(file_content_hash, prompt_id,
model)` and **excludes the template body**, so editing an existing prompt in place silently returns
stale cached responses. A new id also keeps the existing cache valid, so only the new calls are
paid. `src/extraction/llm_extractor.py:34-38` records this in a comment; do not work around it.

**`prompts/redux_slice.jinja2`** — per-file, new id `redux_slices`, appended to `PROMPTS`.
Extracts, from one file: `createSlice` calls (name, `initialState` field names), the reducer keys
with their `PayloadAction<T>` type and the state fields each one writes, `combineReducers` maps,
and plain selector functions of the form `(state: RootState) => state.xxx`. Returns
`ReduxSliceResponse { slices, combinedReducers, selectors }`. Few-shot examples drawn from
`auth.ts` (5 reducers, two payload shapes), `slices/index.ts` (the `combineReducers` map) and
`selectors/index.ts`.

`createSlice` is regular, declarative syntax — a fixed object literal with known keys — which
should make this prompt markedly easier to stabilise than the JSX-reading prompts were.

**`prompts/redux_usage.jinja2`** — cross-file, new id `redux_usage`, appended to
`CROSS_FILE_PROMPTS`. Per component file: which action creators are dispatched (from
`dispatch(addCategory(...))` call sites), which selectors are passed to `useSelector`, and — for
saga files — which actions are watched (`takeLatest`) and which are put (`put`). Returns
`ReduxUsageResponse { dispatches, selectorUses, sagaHandlers }` with the imported symbol name and
its import specifier, leaving resolution to Python.

### Step 2 — Gate both prompts on the project actually using Redux

Four of five repos have no Redux, and a prompt that returns `{}` still costs a call. Two gates:

- **Project gate (cheap, exact):** skip both prompts unless `package.json` lists `react-redux` or
  `redux`. The information is already in the `Library` nodes; at extraction time read it from the
  Stage 1 `extract_libraries` output.
- **File gate for Stage 4:** reuse the existing `_file_has_cross_file_content` pattern in
  `src/extraction/cross_file.py:364-367` — add `_file_has_redux_content`, true when the file's
  Stage 2 `library_usage` result names a redux package. In TakeNote that is **24 of 60 files**.

The project gate means a re-extraction of the four non-Redux repos costs **zero new calls**, and
their graphs are bit-identical. That is what keeps the blast radius to one repo.

> **Trap — do not gate the per-file prompt the same way.** `src/client/selectors/index.ts` imports
> *nothing* from a redux package (`import { RootState } from '@/types'`), yet it defines all five
> selectors. A `library_usage`-based gate drops it, and with it every `USES_SELECTOR` edge and
> therefore every `READS_SLICE`. The gate above is deliberately asymmetric: `redux_slices` runs on
> **all** files of a Redux project (60 calls, $0.74 — cheap enough that the gate is not worth the
> risk), and only the Stage 4 `redux_usage` prompt is file-gated, because dispatching genuinely
> requires importing the action creator. `src/client/utils/helpers.ts` imports `Action` from
> `redux` for a type annotation only, so expect one gated file that yields nothing.

### Step 3 — Resolution, reusing the existing ladder

`DISPATCHES` and `USES_SELECTOR` are import-resolution problems, and the shared
relative → alias → `baseUrl` ladder (`resolve_import_path()` / `resolve_to_manifest_file()`,
`src/extraction/cross_file.py`) already handles TakeNote's `@/slices/note` alias form. Route the
new resolvers through it rather than writing a fourth resolver — the `3ed4db3` commit message is
explicit that four disagreeing resolvers was the bug.

- `dispatch(addCategory(...))` → `addCategory` imported from `@/slices/category` → resolves to
  `src/client/slices/category.ts` → `Redux_Action {uid: "addCategory::category::src/client/slices/category.ts"}`.
- `useSelector(getNotes)` → `getNotes` from `@/selectors` → barrel resolution (already supported)
  → `Redux_Selector`.
- `Redux_Selector.sliceKey` → `Redux_Slice.stateKey` join is a pure property match, no LLM.
- `(FC)-[:READS_SLICE]->(Redux_Slice)` is derived programmatically from `USES_SELECTOR` +
  `READS_SLICE`, in the Stage 4 post-processing block next to the deferred component→hook edges.

### Step 4 — Ingestion

`Redux_Slice`, `Redux_Action` and `DECLARES_ACTION` are within-file: created in Stage 3
(`per_file_ingestion.py`), same shape as `Custom_Hook`. Everything else is Stage 4. Constraints and
indexes on all three `uid`s in `src/graph/schema.py` — remember Memgraph does not auto-index a
constraint, so both statements per label.

---

## Retrieval

The nodes are worthless to the pilot unless the templates return them.

- **`bug_fix.cypher`** — add `OPTIONAL MATCH (anchor)-[:DISPATCHES]->(:Redux_Action)` and
  `(anchor)-[:READS_SLICE]->(:Redux_Slice)`, returning action names with their `payloadType` and
  the slice's `stateFields`. P6's fix does not touch the store, but its test builds one, so the
  context should say which slice `CategoryList` reads.
- **`feature_addition_a.cypher`** — the P2 path. Must return the anchor's dispatched actions **and
  the full action list of every slice it touches**, because "add an action shaped like the
  existing ones" needs the siblings, not just the ones already used.
- **`refactoring.cypher`** — dispatch/selector use is part of a component's blast radius.
- **`src/retrieval/models.py`** — `ComponentContext` gains `dispatched_actions`, `slices_read`;
  `ContextData` needs nothing new.
- **`prompts/generation/format_a.jinja2`** — two new blocks in the target-component section,
  matching the existing `**Hooks used:**` / `**Consumes context:**` style.
- **Budget check.** P2's KG context is 1,532 tokens against a 7,000 cap, so there is ample room;
  the point of the exercise is to spend some of it on the right thing. Re-check the per-template
  truncation in `assembler.py` all the same.

---

## Evaluation and annotation

- `src/evaluation/annotation.py`: add the three labels to `NODE_ORDER` and `FILE_SCOPED_LABELS`
  (all three are file-scoped and carry `filePath`); the new edges need no `EDGE_KEYS` entry since
  none has an identity-bearing property except `DISPATCHES.count`, which is not part of identity.
- `annotation_guide.md`: a section per new type with a decidable rule. The rule for
  `Redux_Action` should be explicit that one reducer key is one item, so annotators do not
  double-count the action creator.
- Regenerate the WP6 sample for TakeNote. Note that `src/client/slices/index.ts` is **already in
  the sample** and currently yields almost no items; after WP11 it yields the `combineReducers`
  map. The stratification will need re-running.
- WP7 needs no code change: `scoring.py` is type-agnostic and aggregates over whatever
  `NODE_ORDER` contains.

---

## Files to touch

Benchmarked against `3ed4db3`, which added **one** node type across 19 files / ~1,450 lines /
53 tests. WP11 is three node types, six edges and two prompts — roughly twice that.

```
prompts/redux_slice.jinja2                        new (~300 lines, few-shot)
prompts/redux_usage.jinja2                        new (~350 lines, few-shot)
src/graph/models.py                               3 node models + 2 response models + extractions
src/graph/schema.py                               3 constraints + 3 indexes
src/graph/queries.py                              3 MERGE_* node + 6 MERGE_* edge templates
src/graph/ingestion.py                            batch wiring
src/extraction/llm_extractor.py                   PROMPTS + CROSS_FILE_PROMPTS entries
src/extraction/per_file_ingestion.py              slice/action/DECLARES_ACTION
src/extraction/cross_file.py                      _file_has_redux_content, 3 resolvers,
                                                  derived READS_SLICE post-processing
src/extraction/pipeline.py                        project-level redux gate
src/retrieval/templates/bug_fix.cypher            +2 OPTIONAL MATCH, +2 return keys
src/retrieval/templates/feature_addition_a.cypher +slice sibling actions
src/retrieval/templates/refactoring.cypher        +blast radius
src/retrieval/templates/cypher_templates.md       document all three
src/retrieval/assembler.py                        rows -> ComponentContext
src/retrieval/models.py                           ComponentContext fields
prompts/generation/format_a.jinja2                2 render blocks
src/evaluation/annotation.py                      NODE_ORDER, FILE_SCOPED_LABELS
docs/phase_1/ReactJS_KG_Schema_details_v2.md      schema v3: 14 node types, 36 relationships
docs/phase_2/ijckg-2026/annotation_guide.md       3 new type rules
CLAUDE.md                                         node/relationship counts, structure table
tests/unit/test_redux_ingestion.py                new
tests/unit/test_redux_resolution.py               new
tests/unit/retrieval/test_redux_templates.py      new
tests/fixtures/                                   slice / selector / saga / container fixtures
```

---

## Cost and wall-clock of the re-extraction

All figures derived from `wp9_cost.md` §1, which is reconciled against the Anthropic console for
18–19 Sep. TakeNote: 644 calls, $8.86, 28.1 min → **$0.0123 per per-file call** (480 calls /
$5.91), **$0.0180 per cross-file call** (164 / $2.95), ~2.6 s per call wall-clock at the
pipeline's concurrency with `call_delay = 0`.

The warm caches are on disk (`.cache/llm_rerun_takenote`, 280K; `.cache/llm_rerun_react-shopping-cart`,
176K), and new `prompt_id`s leave them valid, so the eight existing prompts are cache hits.

| Pass | Calls | USD | Wall-clock |
|---|---|---|---|
| `redux_slices` on TakeNote's 60 files | 60 | $0.74 | ~2.5 min |
| `redux_usage` on the 24 redux-importing files | 24 | $0.43 | ~1 min |
| Stage 4 post-processing + export | 0 | $0 | ~1 min |
| **TakeNote total** | **84** | **≈ $1.17** | **≈ 5 min** |
| Four non-Redux repos (project gate) | 0 | $0 | — |

Add prompt-development calls — the iteration, not the final run. Budget **$10–15** for that from
the `Custom_Hook` precedent, and run it against a two-file subset, not the repo.

**Total re-extraction: ≈ $1, five minutes.** This is the cheap part, and it is worth stating
plainly in WP10: the incremental cost of a schema extension on an already-extracted repo is about
a dollar, because the cache key is per prompt. That is an argument for the architecture, not just
a logistics note.

---

## What re-extracting invalidates

This, not the money, is why WP11 does not belong in the 18–22 Sep window.

| Artifact | Effect | Re-work |
|---|---|---|
| `graph_export/takenote/`, `graph_reruns/takenote/` | new dump, new manifest, new `prompt_set_version` | re-export, commit as a **new** directory; never overwrite |
| WP5 KG arm, P2 / P3 / P6, both models | context changes → results stale | 30 candidates. ≈ $0.36 of API; ~1–1.5 h wall-clock (P2/P3/P6 timeouts are 154 / 175 / 146 s, 3× p95). **New `--run-id`.** |
| WP5 other conditions | untouched — floor, whole-file, BM25 and dense do not read the KG | none |
| WP6 sample + TakeNote annotation files | items change for 6 files | regenerate. **Stale as of 24 Sep: all 28 annotations are now done and WP7 is scored**, so this is no longer free — regenerating the 6 TakeNote files discards finished manual work and re-opens a frozen figure. WP11 now falls on the *after* side of the ordering rule below, which is where it was always meant to land |
| `wp7_extraction_accuracy.*` | new types to score | re-run `scripts/wp7_score.py` |
| `schema_coverage.md` | G1 closes, G3 narrows | rewrite §G1; recount the 32 patch units |
| `wp9_cost.md` §1 | TakeNote's row is now a two-prompt-set graph | add the delta as a separate line; do **not** restate the cold figure, it is console-reconciled |
| CLAUDE.md, schema v2 doc, and every "11 node types / 30 relationships" in the paper | counts change to 14 / 36 | mechanical but must be complete |

**Ordering rule:** WP11 must land either **before** manual annotation starts or **after** WP7 is
scored and frozen. Landing it mid-annotation wastes the annotator's finished files. The calendar
settles this: annotation and WP7 scoring are the critical path on 21–22 Sep and the paper is
written 23–28 Sep from frozen numbers, so by the time WP11 can start, **WP7 is already frozen and
published**. The "after" branch is the only one available, which is the comfortable one — nothing
in this plan is blocked on beating an annotation deadline.

One consequence to carry into the writing leg: the WP7 accuracy figures and the schema counts
(11 node types / 30 relationships) that go into the paper are measured on the **pre-WP11** graph.
That is correct and should not be hedged — but it means WP11 changes numbers the submitted paper
will already state, so the re-extracted TakeNote graph must be committed as a **new** export
directory with its own `prompt_set_version`, never as an overwrite of the graph the paper cites.

---

## Effort and schedule

| Step | Work | Estimate |
|---|---|---|
| 1 | Schema delta: models, constraints, queries, ingestion | 0.5 d |
| 2 | `redux_slice.jinja2` + fixtures + unit tests, iterated on 2 files | 0.5–1 d |
| 3 | `redux_usage.jinja2` + resolvers through the existing ladder + tests | 1 d |
| 4 | Re-extract TakeNote, export, verify counts | 0.5 d (5 min of it is the API) |
| 5 | Retrieval templates, assembler, `format_a`, tests | 0.5 d |
| 6 | WP5 KG re-run on P2/P3/P6, both models, new run-id | 0.5 d |
| 7 | Annotation vocabulary, WP6 regeneration, docs, counts | 0.5 d |
| | **Total** | **3.5–4 days** |

Earliest start is **29 Sep**, after the writing leg. The estimate is working days, not
calendar days, and steps 1–3 are the only ones that need uninterrupted attention.

Prompt iteration (steps 2–3) is the variance. `createSlice` being declarative argues for the low
end; the `Custom_Hook` experience — where the prompt was correct and the *resolver* was the bug —
argues for keeping step 3 at a full day.

**Step 6 is optional but strongly recommended.** Without it the extension is implemented and
unmeasured, and the interesting question — does P2's Qwen KG arm move off 0/5 — goes unanswered.

### A second Redux repo

Half the task set cannot exercise this work, so consider adding one Redux repo with a Docker
harness before step 6. That is its own WP1-sized piece (extraction ≈ $3–9 and 20–30 min by the
`wp9_cost.md` per-file rate, plus Dockerfile, pinning and task curation) and should be decided
separately — but a one-repo, three-task result is thin ground for a schema claim, and it is better
to know that before step 6 than after.

---

## Commits

Separate commit per step, files staged by explicit path, on a branch off `main` — **not** on
`4-phase2-1a-implementation-ijckg-2026`, which is frozen from 22 Sep: the writing leg (23–28 Sep)
reads its artifacts, and the paper cites them.

```
docs(redux)    this plan
feat(redux)    schema: 3 node types, 6 relationships, constraints, MERGE queries
feat(redux)    redux_slice prompt + Stage 3 ingestion + tests
feat(redux)    redux_usage prompt + Stage 4 resolution + derived READS_SLICE + tests
data(redux)    re-extracted takenote graph (new export dir, new prompt_set_version)
feat(redux)    retrieval templates + assembler + format_a
exp(redux)     WP5 KG re-run on P2/P3/P6 (new run-id)
docs(redux)    schema v3, annotation guide, schema_coverage G1, counts
```

---

## Verification

- `uv run pytest tests/unit -q` green, including the three new test modules.
- **The four non-Redux graphs are byte-identical after a re-run.** This is the gate that proves the
  project gate works; diff the dumps.
- TakeNote's new dump contains 5 `Redux_Slice`, 50 `Redux_Action`, 5 `Redux_Selector`, and
  `DISPATCHES` edges covering the 39 measured call sites (allow for the same action dispatched from
  two places collapsing to one edge with `count = 2`).
- `slices/index.ts` yields 5 `stateKey` assignments; no `Redux_Slice` has an empty `stateKey`.
- The 29 existing `USES_LIBRARY_HOOK` edges into `useSelector` / `useDispatch` are **unchanged** —
  the new edges are additive, not a replacement.
- P2's KG context renders the note slice's existing actions and `NoteState`'s fields, and stays
  under the 7,000-token cap.
- A replay of `scripts/wp9_retrieval_timing.py` against the new dump: Cypher time stays in single-
  digit ms (TakeNote is 4.4–6.8 ms today; three OPTIONAL MATCHes should not change the order).

## Risks

| Risk | Fallback |
|---|---|
| `redux_usage` mis-resolves aliased imports | The ladder is shared and tested; add `@/slices/*` cases to `test_base_url_resolution.py` before writing the prompt. |
| Saga extraction proves unreliable | Ship `HANDLES_ACTION` as optional; the component↔action edges are the deliverable and stand without it. |
| The KG arm does not improve on P2 | Report it. A closed schema gap that does not move the outcome is a finding about retrieval, not a failure of extraction — and it is exactly the kind of negative result the gate reviews have recorded before. |
| Scope creep into G2 (plain functions) | `HANDLES_ACTION` anchors on `File` precisely to avoid this. Do not add a function node type in WP11. |
| Re-extraction drifts other repos | The byte-identical check above is a hard gate, not a spot check. |

## Open questions

1. Is `READS_SLICE` at field grain (`noteState.notes`) worth it, or is slice grain enough? Slice
   grain is proposed; field grain needs the `@/types` interfaces, i.e. G3.
2. Should `Redux_Slice` subsume the Context API so `cart-context` and `noteState` share one "state
   container" abstraction? That would make react-shopping-cart exercise the same templates — but it
   is a modelling claim the thesis would have to defend, not an extraction detail.
3. Does a second Redux repo enter before or after the first measured re-run?
