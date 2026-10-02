// ─── ANCHOR CANDIDATES ───────────────────────────────────────────────────────
// Parameters: $projectId (string)
// Retrieval intent: every node a template will accept as an anchor, so that the
//   classifier's raw anchor names can be resolved against what the graph actually
//   holds BEFORE the anchor-scoped templates run.
//
// Used only by the opt-in `anchor_resolution = "hardened"` retriever setting
// (src/retrieval/anchor_resolver.py). The default "strict" path never runs it and
// is byte-identical to what WP5 measured.
//
// Deliberately metadata only — name, uid, filePath, label. 20 rows for
// react-shopping-cart, 48 for TakeNote: one cheap scan, no source, no traversal.
// ─────────────────────────────────────────────────────────────────────────────

MATCH (:Project {projectId: $projectId})<-[:BELONGS_TO]-(f:File)<-[:DEFINED_IN]-(n)
WHERE n:Function_Component OR n:Class_Component OR n:Custom_Hook

RETURN
  n.name            AS name,
  n.uid             AS uid,
  n.filePath        AS filePath,
  labels(n)[0]      AS label
ORDER BY name, filePath
