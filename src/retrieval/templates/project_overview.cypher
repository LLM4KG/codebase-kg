// ─── PROJECT OVERVIEW (last-resort fallback) ─────────────────────────────────
// Parameters: $projectId (string), $overviewLimit (int)
// Retrieval intent: a bounded, metadata-only picture of the project's largest
//   components, for the one case where NO anchor resolved at all.
//
// This is the fallback that `cypher_templates.md` claimed for months and never had
// (corrected 2026-09-21, WP8). It is reached only under
// `anchor_resolution = "hardened"`, only when every anchor is unresolved, and it is
// capped twice: $overviewLimit rows here, and the retriever's token_budget when the
// rows are assembled. It returns NO source code — an unbounded project-wide scan is
// precisely the failure mode the old L5 note predicted.
//
// "Largest" = props + library hooks + custom hooks + state variables. A component
// with the most of those is the one whose interface a task is most likely to touch.
// ─────────────────────────────────────────────────────────────────────────────

MATCH (:Project {projectId: $projectId})<-[:BELONGS_TO]-(f:File)<-[:DEFINED_IN]-(c)
WHERE c:Function_Component OR c:Class_Component

OPTIONAL MATCH (c)-[:ACCEPTS_PROP]->(ap:Prop)
OPTIONAL MATCH (c)-[:USES_LIBRARY_HOOK]->(lh:Library_Hook)
OPTIONAL MATCH (c)-[:USES_CUSTOM_HOOK]->(ch:Custom_Hook)
OPTIONAL MATCH (c)-[:DECLARES_STATE]->(sv:State_Variable)
OPTIONAL MATCH (c)-[:DECLARES_CLASS_STATE]->(csv:State_Variable)

WITH
  c,
  collect(DISTINCT ap.name) AS propNames,
  collect(DISTINCT lh.name) AS libraryHookNames,
  collect(DISTINCT ch.name) AS customHookNames,
  collect(DISTINCT sv.name) AS stateNames,
  collect(DISTINCT csv.name) AS classStateNames

WITH
  c,
  [x IN propNames WHERE x IS NOT NULL]           AS propNames,
  [x IN libraryHookNames WHERE x IS NOT NULL]    AS libraryHookNames,
  [x IN customHookNames WHERE x IS NOT NULL]     AS customHookNames,
  [x IN (stateNames + classStateNames) WHERE x IS NOT NULL] AS stateNames

RETURN
  c.name                                                      AS componentName,
  c.filePath                                                  AS filePath,
  labels(c)[0]                                                AS componentType,
  propNames                                                   AS propNames,
  libraryHookNames + customHookNames                          AS hookNames,
  stateNames                                                  AS stateNames,
  size(propNames) + size(libraryHookNames)
    + size(customHookNames) + size(stateNames)                AS weight
ORDER BY weight DESC, componentName ASC
LIMIT $overviewLimit
