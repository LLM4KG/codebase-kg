# WP6 annotation — takenote · `src/client/slices/index.ts`

<!-- wp6 v1 project=takenote path=src/client/slices/index.ts sha=e0eddbb9a21ae4cf4c4c7c183f29cfd666e08331 graph=graph_export/takenote/full_dump.cypherl prompt_set=72ef9f041851 -->

status: done
annotator: annotator_1

> Guide: `docs/phase_2/ijckg-2026/annotation_guide.md`. Work top to bottom and **finish
> step 1 before you read step 2**. Set `status:` to `done` when the file is finished.

## Step 1 — Read the source, then note what you see (not scored)

List the components, hooks, props, state, handlers, contexts and routes you find, and
what each component renders and uses. Do this *before* looking at step 2.

<!-- wp6:notes -->

<!-- wp6:notes-end -->

Source at `e0eddbb`:

````ts
 1  import { combineReducers, Reducer } from 'redux'
 2  
 3  import authReducer from '@/slices/auth'
 4  import categoryReducer from '@/slices/category'
 5  import noteReducer from '@/slices/note'
 6  import settingsReducer from '@/slices/settings'
 7  import syncReducer from '@/slices/sync'
 8  import { RootState } from '@/types'
 9  
10  const rootReducer: Reducer<RootState> = combineReducers<RootState>({
11    authState: authReducer,
12    categoryState: categoryReducer,
13    noteState: noteReducer,
14    settingsState: settingsReducer,
15    syncState: syncReducer,
16  })
17  
18  export default rootReducer
````

## Step 2 — Review what the extractor found

Set every `[ ]` to `[y]` (correct), `[n]` (wrong) or `[?]` (unsure). An item that is
right but points at the wrong target is `[n]`; add the right one in step 3. Add
` # cause: resolution|llm|schema` or any note after an item if useful.

<!-- wp6:items -->

### LLM-extracted nodes (0)

(none)

### LLM-extracted edges (0)

(none)

### Deterministic (sanity scope) (2)

- [y] N File
- [y] E BELONGS_TO File -> Project:takenote

<!-- wp6:items-end -->

## Step 3 — What the extractor missed

One item per line, in the step-2 syntax, without the checkbox. `@path` defaults to this
file. Examples:

    N Prop:Button::onClick
    E USES_COMPONENT Function_Component:App -> Function_Component:Header@src/Header.tsx

<!-- wp6:missed -->

<!-- wp6:missed-end -->
