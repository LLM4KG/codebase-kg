// ─── FEATURE_ADDITION TEMPLATE — Query A: Anchor + composition ──────────────
// Parameters: $projectId (string), $anchorNames (list<string>)
// Retrieval intent: anchor source + children + props + hooks/state + consumed
//   context. Query B (routing table) runs separately.
// ─────────────────────────────────────────────────────────────────────────────

MATCH (:Project {projectId: $projectId})<-[:BELONGS_TO]-(f:File)<-[:DEFINED_IN]-(anchor)
WHERE (anchor:Function_Component OR anchor:Class_Component)
  AND anchor.name IN $anchorNames

// Children the anchor renders
OPTIONAL MATCH (anchor)-[:USES_COMPONENT]->(child)
WHERE child:Function_Component OR child:Class_Component

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
    filePath: child.filePath,
    uid:      child.uid
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
    name:         ctx.name,
    providerName: provider.name,
    providerFile: providerFile.filePath
  })                                   AS consumedContexts,
  collect(DISTINCT {
    name: childCtx.name
  })                                   AS childConsumedContexts
ORDER BY componentName
