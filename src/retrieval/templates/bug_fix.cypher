// ─── BUG_FIX TEMPLATE ───────────────────────────────────────────────────────
// Parameters: $projectId (string), $anchorNames (list<string>)
// Retrieval intent: anchor source + state/hooks/handlers + direct parents +
//   delegated custom hooks. Routing and context intentionally excluded.
//
// Custom_Hook is an accepted anchor label. The pilot's P1 task is a hook-internal
// bug ("fix decreaseProductQuantity in useCartProducts.ts") and the classifier
// anchors on `useCartProducts`, so a components-only filter matched zero rows and
// the whole query returned empty. Note the label filter was never the primary
// cause — Custom_Hook nodes were absent from the graph entirely; this widening is
// necessary but only useful once extraction actually creates them.
//
// A hook anchor simply has no ACCEPTS_PROP / HAS_HANDLER / PASSES_PROP parents;
// those OPTIONAL MATCHes yield empty collections rather than dropping the row.
// ─────────────────────────────────────────────────────────────────────────────

// Step 1 — Resolve anchor components or hooks within this project
MATCH (:Project {projectId: $projectId})<-[:BELONGS_TO]-(f:File)<-[:DEFINED_IN]-(anchor)
WHERE (anchor:Function_Component OR anchor:Class_Component OR anchor:Custom_Hook)
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

// Step 8 — Consumers of the anchor when it is itself a hook.
//           The hook-side analogue of Step 6's directParents: a hook has no
//           prop-passing parent, but changing its return shape or behaviour
//           still breaks every component calling it. Empty for component anchors.
OPTIONAL MATCH (consumer)-[:USES_CUSTOM_HOOK]->(anchor)
WHERE consumer:Function_Component OR consumer:Class_Component OR consumer:Custom_Hook

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
    eventType:   eh.eventType,
    handlerName: eh.name
  })                                   AS eventHandlers,
  collect(DISTINCT {
    name:     parent.name,
    filePath: parent.filePath,
    uid:      parent.uid
  })                                   AS directParents,
  collect(DISTINCT {
    name:     chook.name,
    filePath: hookFile.filePath
  })                                   AS delegatedHooks,
  collect(DISTINCT {
    name:     consumer.name,
    filePath: consumer.filePath,
    uid:      consumer.uid
  })                                   AS usedByComponents
ORDER BY componentName
