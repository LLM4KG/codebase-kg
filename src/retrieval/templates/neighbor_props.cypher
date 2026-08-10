// ─── NEIGHBOUR PROPS — companion query for all three task types ─────────────
// Parameters: $projectId (string), $neighborUids (list<string>)
// Returns, per neighbour component, the props it accepts and the state it
// declares. The retriever joins this onto the main query's neighbours on uid.
//
// Why this exists: the main templates return neighbours as {name, filePath}
// only, so the rendered "Related Components" section was a heading and a path —
// information the import list already carried. Measured cost of that omission:
// P2's five kg_augmented candidates all failed to build on
// `TS2741: Property 'dataTestID' is missing ... but required in NoteListButtonProps`,
// while the whole-file oracle (which sees the component body) passed 5/5. The
// prop was in the KG the whole time and simply never reached the prompt.
//
// Split out rather than folded into the parent queries for the same reason as
// refactoring_caller_props.cypher: a nested list inside a collected map under
// DISTINCT is the aggregation shape Memgraph handles least predictably. Single
// level of collect() per field here.
// ─────────────────────────────────────────────────────────────────────────────

MATCH (:Project {projectId: $projectId})<-[:BELONGS_TO]-(:File)<-[:DEFINED_IN]-(c)
WHERE (c:Function_Component OR c:Class_Component)
  AND c.uid IN $neighborUids

// Props the neighbour accepts — the contract a caller must satisfy.
OPTIONAL MATCH (c)-[:ACCEPTS_PROP]->(p:Prop)

// State it declares. Both labels: function components use DECLARES_STATE,
// class components DECLARES_CLASS_STATE.
OPTIONAL MATCH (c)-[:DECLARES_STATE|DECLARES_CLASS_STATE]->(sv:State_Variable)

RETURN
  c.uid AS uid,
  collect(DISTINCT {
    name:       p.name,
    type:       p.type,
    isRequired: p.isRequired
  })    AS props,
  collect(DISTINCT {
    name: sv.name,
    type: sv.type
  })    AS stateVars
