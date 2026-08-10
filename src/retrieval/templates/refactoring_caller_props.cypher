// ─── REFACTORING TEMPLATE — caller props (L3 split query) ───────────────────
// Parameters: $projectId (string), $anchorNames (list<string>)
// Returns, per (anchor, caller), the list of prop names the caller passes to the
// anchor. Single-level collect() — avoids the nested-aggregation limitation. The
// retriever joins this onto the main refactoring query's callers on caller.uid.
// ─────────────────────────────────────────────────────────────────────────────

MATCH (:Project {projectId: $projectId})<-[:BELONGS_TO]-(:File)<-[:DEFINED_IN]-(anchor)
WHERE (anchor:Function_Component OR anchor:Class_Component)
  AND anchor.name IN $anchorNames
MATCH (caller)-[pp:PASSES_PROP]->(anchor)
WHERE caller:Function_Component OR caller:Class_Component

RETURN
  anchor.name              AS componentName,
  caller.uid               AS callerUid,
  collect(pp.propName)     AS propsPassed
