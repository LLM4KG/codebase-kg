// ─── FEATURE_ADDITION TEMPLATE — Query B: Routing table ─────────────────────
// Parameters: $projectId (string)
// Retrieval intent: full project routing table (project-wide, not anchor-scoped).
//   Surfaced as the Format A cross-cutting notes section.
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
