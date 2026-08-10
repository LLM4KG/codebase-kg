# Cypher Template Content — KG-Augmented Retriever

**Status:** First-pass design — April 2026  
**Resolves:** Open issue #2 in `phase2_implementation_plan.md`  
**Companion documents:** `ReactJS_KG_Schema_details_v2.md`, `phase2_design_summary.md`

---

## 1. How templates fit in the pipeline

The KG-augmented retriever runs a two-step planner before every generation call:

1. **Classifier + anchor extractor** (LLM call): receives the raw task spec and returns `task_type` (`bug_fix | feature_addition | refactoring`) plus `anchor_names` (component or hook names mentioned or clearly implied in the spec) and optionally `anchor_routes` (URL path strings).

2. **Cypher template dispatch** (this document): `task_type` selects one of the three templates below. `anchor_names`, `anchor_routes`, and `project_id` are bound as parameters. The query is executed against Memgraph.

3. **Context assembler**: receives query results, reads full source from disk using the `filePath` fields returned, and renders the Format A hybrid-plus-source prompt block.

The templates are retrieval queries — they read from the graph, never write. Each is stored as a parameterized Cypher string (a `.cypher` file under `retrieval/templates/`) and executed via the Memgraph GQL Python client with `session.run(query, parameters)`.

---

## 2. Input contract (parameters bound at dispatch time)

All three templates share the same parameter signature:

| Parameter | Type | Required | Description |
|---|---|---|---|
| `$projectId` | string | always | Scopes results to one project. Prevents cross-project name collisions. |
| `$anchorNames` | list[string] | always | Component (or custom hook) names extracted from the spec. May be empty if the classifier finds no anchors (templates handle this gracefully). |
| `$anchorRoutes` | list[string] | optional | URL path strings extracted from the spec (e.g., `["/notes/trash"]`). Passed to all three templates; only `feature_addition` actively uses it. |

**On empty `$anchorNames`:** If the anchor extractor returns no names, the templates fall back to returning project-wide structural summaries (routing table, context providers, top-level composition). This is worse context than anchor-scoped context, but better than nothing. The fallback path is noted in each template below.

---

## 3. Schema conventions used by all templates

- Components are either `Function_Component` or `Class_Component`. Queries must handle both labels. Pattern used throughout: `MATCH (c) WHERE (c:Function_Component OR c:Class_Component)`.
- Project scoping via the path: `(:Project {projectId: $projectId})<-[:BELONGS_TO]-(:File)<-[:DEFINED_IN]-(component)`.
- State in function components: `DECLARES_STATE → State_Variable`. State in class components: `DECLARES_CLASS_STATE → State_Variable`.
- Hook usage: `USES_LIBRARY_HOOK → Library_Hook`, `USES_CUSTOM_HOOK → Custom_Hook`. Only `Function_Component` and `Custom_Hook` nodes have these edges; class components do not.
- All returned nodes include their `filePath` property so the context assembler can read source from disk.

---

## 4. Template 1 — `bug_fix`

### Retrieval intent

Bug fixes are usually localised to one or two components. The retriever needs:
- The full source of the anchor component(s) — the primary read target.
- Their state and hook usage — the most common sites of bugs.
- Their event handlers — second most common bug site.
- Props they accept — to understand the caller's contract.
- Their direct parents — to trace data flow upward and check whether the bug is caused by a bad value being passed in rather than internal logic.
- Custom hooks they delegate to — because extracting a hook is a common refactoring that leaves bugs in the hook body.

The routing table and context graph are **not** retrieved for bug fixes. They are architecturally stable across a bug fix and add noise.

### Query

```cypher
// ─── BUG_FIX TEMPLATE ───────────────────────────────────────────────────────
// Parameters: $projectId (string), $anchorNames (list<string>)
// ─────────────────────────────────────────────────────────────────────────────

// Step 1 — Resolve anchor components within this project
MATCH (:Project {projectId: $projectId})<-[:BELONGS_TO]-(f:File)<-[:DEFINED_IN]-(anchor)
WHERE (anchor:Function_Component OR anchor:Class_Component)
  AND anchor.name IN $anchorNames

// Step 2 — Props the anchor accepts (caller contract)
OPTIONAL MATCH (anchor)-[:ACCEPTS_PROP]->(ap:Prop)

// Step 3 — Hook usage (function components only; class components have no hooks)
OPTIONAL MATCH (anchor)-[:USES_LIBRARY_HOOK]->(lh:Library_Hook)
OPTIONAL MATCH (anchor)-[:USES_CUSTOM_HOOK]->(ch:Custom_Hook)

// Step 4 — State (function and class variants)
OPTIONAL MATCH (anchor)-[:DECLARES_STATE]->(sv:State_Variable)
OPTIONAL MATCH (anchor)-[:DECLARES_CLASS_STATE]->(csv:State_Variable)

// Step 5 — Event handlers
OPTIONAL MATCH (anchor)-[:HAS_HANDLER]->(eh:EventHandler)

// Step 6 — Direct parents passing props into the anchor
//           (needed to trace whether the bug originates upstream)
OPTIONAL MATCH (parent)-[:PASSES_PROP]->(anchor)
WHERE parent:Function_Component OR parent:Class_Component

// Step 7 — Custom hooks the anchor delegates to
//           (bugs can live inside the hook body, not the component)
OPTIONAL MATCH (anchor)-[:USES_CUSTOM_HOOK]->(chook:Custom_Hook)
OPTIONAL MATCH (chook)-[:DEFINED_IN]->(hookFile:File)

RETURN
  anchor.name                          AS componentName,
  anchor.filePath                      AS filePath,
  labels(anchor)[0]                    AS componentType,
  collect(DISTINCT {
    name:       ap.name,
    type:       ap.type,
    isRequired: ap.isRequired
  })                                   AS acceptedProps,
  collect(DISTINCT {
    name:   lh.name,
    source: lh.source
  })                                   AS libraryHooks,
  collect(DISTINCT {
    name:     ch.name,
    filePath: ch.filePath
  })                                   AS customHooks,
  collect(DISTINCT {
    name:         sv.name,
    type:         sv.type,
    defaultValue: sv.defaultValue
  })                                   AS stateVars,
  collect(DISTINCT {
    name:         csv.name,
    type:         csv.type,
    defaultValue: csv.defaultValue
  })                                   AS classStateVars,
  collect(DISTINCT {
    eventType: eh.eventType,
    handlerName: eh.handlerName
  })                                   AS eventHandlers,
  collect(DISTINCT {
    name:     parent.name,
    filePath: parent.filePath
  })                                   AS directParents,
  collect(DISTINCT {
    name:     chook.name,
    filePath: hookFile.filePath
  })                                   AS delegatedHooks
ORDER BY componentName
```

### Fallback (empty `$anchorNames`)

If `$anchorNames` is empty, drop the `AND anchor.name IN $anchorNames` predicate. This returns all components in the project — token-budget truncation in the context assembler will keep only the top-k by component size (number of state variables + hooks). This fallback is low-quality; the classifier should be iterated before relying on it at scale.

### What the context assembler does with this

For each row:
1. Read full source from `filePath`.
2. Annotate inline: mark which state variables and hooks are present (derived from `stateVars`, `libraryHooks`, `customHooks`).
3. Read source of each `delegatedHook.filePath`.
4. For each `directParent`, include a one-line summary: `"<ParentName> passes props: [prop names retrieved via separate ACCEPTS_PROP query or returned above]"`. Parent source is **not** included unless it also appears in `$anchorNames`.

---

## 5. Template 2 — `feature_addition`

### Retrieval intent

Feature additions require knowing the surrounding architecture — what already exists — so the new code integrates cleanly. The retriever needs:
- Anchor components and their full source.
- Their direct children (to understand the composition area where the new feature slots in).
- Props flowing into children (the interface convention to follow when wiring up the new feature).
- Hook and state patterns used by the anchors (so the new code follows the same idioms).
- Any context the anchor or its children consume (a new feature may need the same context).
- The full routing table for the project (feature additions frequently add a new route; the LLM needs to know the existing path namespace and router component location).
- Sibling routes at the same nesting level (for structural consistency).

### Query

This template runs as **two sequential queries**. Two queries are cleaner than one because the routing subgraph is project-wide rather than anchor-scoped, and combining them in a single RETURN would create a cross-product.

#### Query A — Anchor and composition context

```cypher
// ─── FEATURE_ADDITION TEMPLATE — Query A: Anchor + composition ──────────────
// Parameters: $projectId (string), $anchorNames (list<string>)
// ─────────────────────────────────────────────────────────────────────────────

MATCH (:Project {projectId: $projectId})<-[:BELONGS_TO]-(f:File)<-[:DEFINED_IN]-(anchor)
WHERE (anchor:Function_Component OR anchor:Class_Component)
  AND anchor.name IN $anchorNames

// Children the anchor renders
OPTIONAL MATCH (anchor)-[:USES_COMPONENT]->(child)
WHERE child:Function_Component OR child:Class_Component

// Props the anchor passes to each child
OPTIONAL MATCH (anchor)-[:PASSES_PROP]->(child)

// Props the anchor itself accepts (from its own parent)
OPTIONAL MATCH (anchor)-[:ACCEPTS_PROP]->(ap:Prop)

// Hook patterns in the anchor
OPTIONAL MATCH (anchor)-[:USES_LIBRARY_HOOK]->(lh:Library_Hook)
OPTIONAL MATCH (anchor)-[:USES_CUSTOM_HOOK]->(ch:Custom_Hook)

// State declared by the anchor
OPTIONAL MATCH (anchor)-[:DECLARES_STATE]->(sv:State_Variable)

// Context the anchor or its children consume
//   (a new feature may need to consume the same context)
OPTIONAL MATCH (anchor)-[:CONSUMES_CONTEXT]->(ctx:Context)
OPTIONAL MATCH (child)-[:CONSUMES_CONTEXT]->(childCtx:Context)

// Who provides the context (so context assembler can include its filePath)
OPTIONAL MATCH (provider)-[:PROVIDES_CONTEXT]->(ctx)
WHERE provider:Function_Component OR provider:Class_Component
OPTIONAL MATCH (provider)-[:DEFINED_IN]->(providerFile:File)

RETURN
  anchor.name                          AS componentName,
  anchor.filePath                      AS filePath,
  labels(anchor)[0]                    AS componentType,
  collect(DISTINCT {
    name:     child.name,
    filePath: child.filePath
  })                                   AS children,
  collect(DISTINCT {
    name:       ap.name,
    type:       ap.type,
    isRequired: ap.isRequired
  })                                   AS acceptedProps,
  collect(DISTINCT {
    name:   lh.name,
    source: lh.source
  })                                   AS libraryHooks,
  collect(DISTINCT {
    name:     ch.name,
    filePath: ch.filePath
  })                                   AS customHooks,
  collect(DISTINCT {
    name:         sv.name,
    type:         sv.type,
    defaultValue: sv.defaultValue
  })                                   AS stateVars,
  collect(DISTINCT {
    name:           ctx.name,
    providerName:   provider.name,
    providerFile:   providerFile.filePath
  })                                   AS consumedContexts,
  collect(DISTINCT {
    name: childCtx.name
  })                                   AS childConsumedContexts
ORDER BY componentName
```

#### Query B — Full routing table

```cypher
// ─── FEATURE_ADDITION TEMPLATE — Query B: Routing table ─────────────────────
// Parameters: $projectId (string)
// ─────────────────────────────────────────────────────────────────────────────

MATCH (:Project {projectId: $projectId})<-[:BELONGS_TO]-(:File)<-[:DEFINED_IN]-(router)
WHERE router:Function_Component OR router:Class_Component
MATCH (router)-[r:ROUTES_TO]->(target)
WHERE target:Function_Component OR target:Class_Component

RETURN
  router.name                          AS routerComponent,
  router.filePath                      AS routerFile,
  r.path                               AS routePath,
  r.isNested                           AS isNested,
  r.isProtected                        AS isProtected,
  r.isLazy                             AS isLazy,
  target.name                          AS targetComponent,
  target.filePath                      AS targetFile
ORDER BY routerComponent, routePath
```

### What the context assembler does with this

1. Read full source for each anchor from `filePath`.
2. For each child, include a brief structural summary: component name, file path, accepted props. Child source is included only if the child is itself in `$anchorNames` or if the token budget has remaining headroom.
3. Render Query B results as a compact routing table in the prompt (the "Cross-cutting notes" section of Format A). Include `routerFile` so the LLM knows where to add the new route.
4. If `$anchorRoutes` was provided by the classifier (e.g., the spec mentions `/notes/trash`), annotate the routing table with a note: `"⚠ The spec references route '<path>' — not yet present in the routing table above."` This primes the LLM to add it.
5. Include context provider file paths (from `providerFile`) in a one-line cross-cutting note: `"<ContextName> is provided by <ProviderName> at <providerFile>; consumers may useContext(<ContextName>) without prop-drilling."` Do not include provider source unless it is also an anchor.

---

## 6. Template 3 — `refactoring`

### Retrieval intent

Refactoring tasks reshape a component's internal structure without changing its observable behaviour from the caller's perspective. The three most common patterns in React codebases are:

- **Hook extraction**: pulling state + effects out of a component into a reusable `Custom_Hook`.
- **Component decomposition**: splitting a large component into smaller sub-components.
- **Prop interface cleanup**: collapsing or restructuring how props are passed.

All three patterns have the same critical risk: breaking callers. The retriever therefore emphasises **caller context** more heavily than the other two templates. It needs:
- The anchor component's full source.
- Its complete prop interface (what callers depend on).
- **All callers** that use the anchor via `USES_COMPONENT` or receive props from it — these must be returned with file paths so the LLM knows the blast radius of any interface change.
- Its current hook + state structure (this is the internal structure being refactored).
- Any custom hooks it already delegates to (to avoid creating a hook that duplicates an existing one).
- Its children (component decomposition must know the existing subtree before splitting).
- Event handlers (often inlined logic that is a candidate for extraction).

### Query

```cypher
// ─── REFACTORING TEMPLATE ────────────────────────────────────────────────────
// Parameters: $projectId (string), $anchorNames (list<string>)
// ─────────────────────────────────────────────────────────────────────────────

MATCH (:Project {projectId: $projectId})<-[:BELONGS_TO]-(f:File)<-[:DEFINED_IN]-(anchor)
WHERE (anchor:Function_Component OR anchor:Class_Component)
  AND anchor.name IN $anchorNames

// ── Prop interface ──
OPTIONAL MATCH (anchor)-[:ACCEPTS_PROP]->(ap:Prop)

// ── All callers (CRITICAL for refactoring — these are the blast-radius components) ──
OPTIONAL MATCH (caller)-[:USES_COMPONENT]->(anchor)
WHERE caller:Function_Component OR caller:Class_Component
OPTIONAL MATCH (caller)-[:DEFINED_IN]->(callerFile:File)

// Props each caller passes to the anchor
//   (shows which of the anchor's props are actually used by each caller)
OPTIONAL MATCH (caller)-[pp:PASSES_PROP]->(anchor)

// ── Internal hook + state structure (the refactoring target) ──
OPTIONAL MATCH (anchor)-[:USES_LIBRARY_HOOK]->(lh:Library_Hook)
OPTIONAL MATCH (anchor)-[:USES_CUSTOM_HOOK]->(ch:Custom_Hook)
OPTIONAL MATCH (ch)-[:DEFINED_IN]->(chFile:File)
OPTIONAL MATCH (anchor)-[:DECLARES_STATE]->(sv:State_Variable)
OPTIONAL MATCH (anchor)-[:DECLARES_CLASS_STATE]->(csv:State_Variable)

// ── Event handlers (common extraction candidates) ──
OPTIONAL MATCH (anchor)-[:HAS_HANDLER]->(eh:EventHandler)

// ── Children (needed for decomposition tasks) ──
OPTIONAL MATCH (anchor)-[:USES_COMPONENT]->(child)
WHERE child:Function_Component OR child:Class_Component

// Props the anchor passes to each child
OPTIONAL MATCH (anchor)-[cpp:PASSES_PROP]->(child)

RETURN
  anchor.name                          AS componentName,
  anchor.filePath                      AS filePath,
  labels(anchor)[0]                    AS componentType,
  // Prop interface
  collect(DISTINCT {
    name:       ap.name,
    type:       ap.type,
    isRequired: ap.isRequired
  })                                   AS acceptedProps,
  // Caller blast radius
  collect(DISTINCT {
    name:         caller.name,
    filePath:     callerFile.filePath,
    propsPassed:  collect(pp.propName)
  })                                   AS callers,
  // Internal structure
  collect(DISTINCT {
    name:   lh.name,
    source: lh.source
  })                                   AS libraryHooks,
  collect(DISTINCT {
    name:     ch.name,
    filePath: chFile.filePath
  })                                   AS customHooks,
  collect(DISTINCT {
    name:         sv.name,
    type:         sv.type,
    defaultValue: sv.defaultValue,
    setterName:   sv.setterName
  })                                   AS stateVars,
  collect(DISTINCT {
    name:         csv.name,
    type:         csv.type,
    defaultValue: csv.defaultValue
  })                                   AS classStateVars,
  collect(DISTINCT {
    eventType:   eh.eventType,
    handlerName: eh.handlerName
  })                                   AS eventHandlers,
  // Children
  collect(DISTINCT {
    name:        child.name,
    filePath:    child.filePath,
    propsPassed: collect(cpp.propName)
  })                                   AS children
ORDER BY componentName
```

### What the context assembler does with this

1. Read full source of each anchor.
2. For every caller in `callers`, include a brief header: `"<CallerName> (<callerFile>) uses <AnchorName> and passes: [propsPassed]"`. Caller source is included only if the token budget has remaining headroom after the anchor source. Callers are sorted by `propsPassed` length descending (most-coupled callers first).
3. Render the cross-cutting note: `"⚠ Refactoring <AnchorName>'s prop interface will require updating <N> caller(s): [caller names]."` If N > 0, the LLM is explicitly warned not to silently break callers.
4. Include the existing custom hook source (`chFile.filePath`) if one exists — this tells the LLM the hook already exists and should be extended rather than duplicated.

---

## 7. Return shape summary

The context assembler receives a list of result rows per query. Each row contains `filePath` fields — these are the only fields used to access disk. All other fields are metadata rendered inline in the Format A prompt block.

| Template | Primary source reads | Metadata fields |
|---|---|---|
| `bug_fix` | anchor, delegated hooks | accepted props, library/custom hooks, state vars, event handlers, direct parent names |
| `feature_addition` (A) | anchor, context providers (if budget) | children (name+path), accepted props, hooks, state vars, consumed contexts |
| `feature_addition` (B) | — (no source) | full routing table (router name, file, path, target name, target file) |
| `refactoring` | anchor, existing custom hooks, callers (if budget) | accepted props, caller names+files+propsPassed, hooks, state vars, event handlers, children+propsPassed |

---

## 8. Token-budget truncation rules

The context assembler is responsible for staying within the 6–8K token budget shared across conditions. Per-template truncation priority:

**bug_fix** (keep in order, drop from bottom if over budget):
1. Anchor source
2. Delegated hook source(s)
3. Accepted props metadata block
4. State variables + library hooks metadata block
5. Event handlers metadata block
6. Direct parent summary lines

**feature_addition** (keep in order, drop from bottom if over budget):
1. Anchor source
2. Routing table (Query B) — always included even at high cost; it is the unique KG value-add for this task type
3. Children metadata block (names, props accepted, file paths)
4. Context notes
5. Child source (if budget remains)
6. Provider source (never; too rarely relevant)

**refactoring** (keep in order, drop from bottom if over budget):
1. Anchor source
2. Caller blast-radius summary lines (names + propsPassed; no caller source unless budget allows)
3. Existing custom hook source (if any)
4. Internal structure metadata block (hooks, state, event handlers)
5. Children + propsPassed metadata block
6. Caller source (rarely; only if one caller and budget allows)

---

## 9. First-pass limitations and expected iteration points

These templates are designed to be good enough for the Phase 1a validation pilot. They will need iteration based on observed failure modes. Known limitations:

**L1 — No two-hop composition traversal.**  
Templates currently retrieve only direct parents and children. A bug in a grandchild component, or a feature that requires touching a grandparent's state, won't surface the full path. Iteration option: add configurable depth parameter (default 1, try 2 on pilot failures involving deeply nested components).

**L2 — Custom hook internals not deeply retrieved.**  
For `bug_fix` and `refactoring`, the query returns the hook's `filePath` but does not traverse the hook's own `DECLARES_STATE` or `USES_LIBRARY_HOOK` edges. The context assembler reads the hook source from disk, which implicitly covers this — but the metadata summary won't include the hook's state vars unless a follow-up query is run. Low priority for first-pass; revisit if pilot failures suggest the LLM needed hook-internal metadata explicitly structured rather than embedded in source.

**L3 — `PASSES_PROP` inside `collect()` with variable scoping.**  
The nested `collect(pp.propName)` inside the outer `collect(DISTINCT {...})` in the refactoring template may produce unexpected results in some Memgraph versions. If query execution returns malformed prop lists, split the caller subquery into a separate query (similar to the feature_addition two-query approach) and join on `caller.uid` in Python.

**L4 — Name collisions across files.**  
`$anchorNames` is matched by `anchor.name IN $anchorNames` with project scoping, but a project can legitimately have two components with the same name in different files (e.g., a `Button` in `components/` and a `Button` in `ui/`). The template returns both rows. The context assembler currently uses both; if the token budget is tight, it will drop the second. This can cause the wrong `Button` to be included. Iteration option: have the classifier return `name::filePath` UIDs when the spec contains enough context to disambiguate; fall back to name-only when not.

**L5 — Empty anchor names fallback is low-quality.**  
If the task classifier fails to extract anchors, all three templates degrade to project-wide scans. This will almost always blow the token budget and require heavy truncation, leaving only the largest components. Track classifier accuracy as a diagnostic metric from pilot run 1.

**L6 — Routing table in `feature_addition` is always full.**  
For large projects (TakeNote has 41 source files and multiple routes), the full routing table may consume a disproportionate share of the token budget. Iteration option: if `$anchorRoutes` is provided, first return only sibling routes (same nesting level, same router component), then extend to full table only if budget allows.

---

## 10. File locations

| File | Location |
|---|---|
| Bug fix template | `retrieval/templates/bug_fix.cypher` |
| Feature addition template A | `retrieval/templates/feature_addition_a.cypher` |
| Feature addition template B | `retrieval/templates/feature_addition_b.cypher` |
| Refactoring template | `retrieval/templates/refactoring.cypher` |
| Caller props (refactoring companion) | `retrieval/templates/refactoring_caller_props.cypher` |
| Neighbour props (all-type companion) | `retrieval/templates/neighbor_props.cypher` |
| Context assembler | `retrieval/assembler.py` |
| Classifier prompt | `retrieval/prompts/classifier.txt` |

Template files contain only the raw Cypher. The Python retriever binds `$projectId`, `$anchorNames`, and `$anchorRoutes` from the parsed classifier response before executing.

---

---

## 11. Iteration notes

### 2026-07-30 — neighbours carry their props (`neighbor_props.cypher`)

All three primary templates returned neighbours as `{name, filePath}`, so the rendered
"Related Components" section was a heading and a path — information the anchor's own import
list already carried. The 2026-07-23 gate review flagged it as a rendering defect that was
"cheap to fix now"; the 2026-07-30 re-measurement attached a price to it.

**Measured cost.** P2's five `kg_augmented` candidates all failed to build on
`TS2741: Property 'dataTestID' is missing in type '{ children; label; handler }' but required
in type 'NoteListButtonProps'` — while the whole-file oracle, which sees the component body,
passed P2 5/5. The prop was in the KG the whole time and never reached the prompt.

**Fix.** New companion query `neighbor_props.cypher` (`$projectId`, `$neighborUids` → `uid`,
`props`, `stateVars`), run for **every** task type once the primary rows are in hand and joined
in the assembler on `uid`. Same split-query pattern as `refactoring_caller_props.cypher`, and for
the same reason: a nested list inside a collected map under `DISTINCT` is the aggregation shape
Memgraph handles least predictably. `feature_addition_a` and `bug_fix` now also select
`uid` on their neighbour collects; the assembler falls back to the `name::filePath` composite
when a template omits it.

`isRequired` is carried through and rendered on its own `- Required:` line: "there is a
dataTestID prop" and "dataTestID is required" are different instructions, and it was the
required-ness that broke the build.

**Truncation.** §8's ladders gain a *clear neighbour props/state* rung immediately before the
rung that removes those neighbours outright — reached only when the alternative is losing the
section entirely. Deliberately not earlier: a bare name-and-path is close to worthless, which is
the defect being fixed, so trading props away to keep names is only worth doing last.

Measured effect on P2's rendered context: 1,163 → **1,235 tokens** (+6%), against a 7,000 budget.

### 2026-07 — L3 resolved (nested `collect()` split); `eh.handlerName` → `eh.name`

During Work item 3 implementation the templates were smoke-tested against the loaded
pilot KGs. Two first-pass issues were fixed:

- **L3 (confirmed and resolved).** The refactoring template's `propsPassed: collect(pp.propName)`
  nested inside `collect(DISTINCT {...})` was rejected by Memgraph 3.x:
  *"Using aggregation functions inside aggregation functions is not allowed."* Fix applied:
  `refactoring.cypher` now returns `callers`/`children` with `uid` and **without** `propsPassed`;
  a new single-level query `refactoring_caller_props.cypher` returns `(callerUid, collect(propName))`,
  and `kg_retriever.py` joins the two on `caller.uid`. The context assembler uses the joined props
  to sort callers by coupling and to enrich the ⚠ caller-blast-radius note. This is the split-query
  pattern the L3 note anticipated.

- **`eh.handlerName` did not exist.** The `bug_fix` and `refactoring` templates returned
  `handlerName: eh.handlerName`, but `EventHandler` nodes carry `name` + `eventType` only. Changed to
  `handlerName: eh.name` (output key preserved). Verified non-null against the pilot KG.

**Operational note:** the two pilot CYPHERL dumps cannot be co-loaded into one Memgraph database —
global `Library` nodes (keyed by `name`, e.g. `axios`) collide on the unique constraint and abort the
second dump. For per-project query smoke-testing, load one project per fresh database.

---

*End of document. Append iteration notes as pilot failures are diagnosed; do not rewrite first-pass templates — record replacements as versioned updates.*
