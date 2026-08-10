// ─── REFACTORING TEMPLATE ────────────────────────────────────────────────────
// Parameters: $projectId (string), $anchorNames (list<string>)
// Retrieval intent: anchor source + prop interface + ALL callers (blast radius) +
//   internal hook/state structure + event handlers + children.
//
// NOTE (L3 — RESOLVED): the original design nested `collect(pp.propName)` inside
// `collect(DISTINCT {...})`, which Memgraph rejects ("aggregation functions inside
// aggregation functions is not allowed"). Fix: this query returns callers/children
// WITHOUT propsPassed (carrying caller.uid / child.uid instead), and the per-caller
// props are fetched by refactoring_caller_props.cypher and joined on uid in Python.
// ─────────────────────────────────────────────────────────────────────────────

MATCH (:Project {projectId: $projectId})<-[:BELONGS_TO]-(f:File)<-[:DEFINED_IN]-(anchor)
WHERE (anchor:Function_Component OR anchor:Class_Component)
  AND anchor.name IN $anchorNames

// ── Prop interface ──
OPTIONAL MATCH (anchor)-[:ACCEPTS_PROP]->(ap:Prop)

// ── All callers (CRITICAL for refactoring — the blast-radius components) ──
OPTIONAL MATCH (caller)-[:USES_COMPONENT]->(anchor)
WHERE caller:Function_Component OR caller:Class_Component
OPTIONAL MATCH (caller)-[:DEFINED_IN]->(callerFile:File)

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
  // Caller blast radius (propsPassed joined separately — see note above)
  collect(DISTINCT {
    name:     caller.name,
    filePath: callerFile.filePath,
    uid:      caller.uid
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
    handlerName: eh.name
  })                                   AS eventHandlers,
  // Children
  collect(DISTINCT {
    name:     child.name,
    filePath: child.filePath,
    uid:      child.uid
  })                                   AS children
ORDER BY componentName
