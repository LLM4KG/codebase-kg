"""Cypher MERGE/UNWIND query templates for Memgraph."""

from __future__ import annotations

# ──────────────────────────────────────────────────────
# Stage 1: Programmatic nodes
# ──────────────────────────────────────────────────────

MERGE_PROJECT = """
MERGE (p:Project {projectId: $projectId})
ON CREATE SET p.name = $name, p.description = $description, p.file_path = $file_path
ON MATCH SET p.name = $name, p.description = $description, p.file_path = $file_path
RETURN p;
"""

MERGE_FILE_BATCH = """
UNWIND $files AS f
MERGE (file:File {filePath: f.filePath})
ON CREATE SET file.name = f.name, file.modifiedAt = f.modifiedAt
ON MATCH SET file.name = f.name, file.modifiedAt = f.modifiedAt;
"""

MERGE_BELONGS_TO_BATCH = """
UNWIND $filePaths AS fp
MATCH (f:File {filePath: fp})
MATCH (p:Project {projectId: $projectId})
MERGE (f)-[:BELONGS_TO]->(p);
"""

MERGE_LIBRARY_BATCH = """
UNWIND $libraries AS lib
MERGE (l:Library {name: lib.name})
ON CREATE SET l.version = lib.version, l.category = lib.category
ON MATCH SET l.version = lib.version, l.category = lib.category;
"""

MERGE_DEPENDS_ON_BATCH = """
UNWIND $deps AS d
MATCH (p:Project {projectId: $projectId})
MATCH (l:Library {name: d.name})
MERGE (p)-[r:DEPENDS_ON]->(l)
SET r.dependencyType = d.dependencyType;
"""

# ──────────────────────────────────────────────────────
# Stage 3: Per-file LLM result nodes
# ──────────────────────────────────────────────────────

MERGE_FUNCTION_COMPONENT = """
MERGE (fc:Function_Component {uid: $uid})
ON CREATE SET
    fc.name = $name, fc.filePath = $filePath, fc.syntax = $syntax,
    fc.usesHooks = $usesHooks, fc.returnsJSX = $returnsJSX,
    fc.exportType = $exportType, fc.isRoot = false
ON MATCH SET
    fc.name = $name, fc.filePath = $filePath, fc.syntax = $syntax,
    fc.usesHooks = $usesHooks, fc.returnsJSX = $returnsJSX,
    fc.exportType = $exportType;
"""

MERGE_CLASS_COMPONENT = """
MERGE (cc:Class_Component {uid: $uid})
ON CREATE SET
    cc.name = $name, cc.filePath = $filePath,
    cc.extendsClass = $extendsClass, cc.returnsJSX = $returnsJSX,
    cc.exportType = $exportType, cc.isRoot = false,
    cc.hasConstructor = $hasConstructor, cc.lifecycleMethods = $lifecycleMethods
ON MATCH SET
    cc.name = $name, cc.filePath = $filePath,
    cc.extendsClass = $extendsClass, cc.returnsJSX = $returnsJSX,
    cc.exportType = $exportType,
    cc.hasConstructor = $hasConstructor, cc.lifecycleMethods = $lifecycleMethods;
"""

MERGE_CUSTOM_HOOK = """
MERGE (ch:Custom_Hook {uid: $uid})
ON CREATE SET ch.name = $name, ch.filePath = $filePath, ch.exportType = $exportType
ON MATCH SET ch.name = $name, ch.filePath = $filePath, ch.exportType = $exportType;
"""

MERGE_LIBRARY_HOOK = """
MERGE (lh:Library_Hook {uid: $uid})
ON CREATE SET lh.name = $name, lh.source = $source
ON MATCH SET lh.name = $name, lh.source = $source;
"""

MERGE_PROP = """
MERGE (pr:Prop {uid: $uid})
ON CREATE SET
    pr.name = $name, pr.componentName = $componentName,
    pr.filePath = $filePath, pr.type = $type, pr.isRequired = $isRequired
ON MATCH SET
    pr.name = $name, pr.componentName = $componentName,
    pr.filePath = $filePath, pr.type = $type, pr.isRequired = $isRequired;
"""

MERGE_STATE_VARIABLE = """
MERGE (sv:State_Variable {uid: $uid})
ON CREATE SET
    sv.name = $name, sv.setterName = $setterName, sv.type = $type,
    sv.defaultValue = $defaultValue, sv.filePath = $filePath,
    sv.componentName = $componentName
ON MATCH SET
    sv.name = $name, sv.setterName = $setterName, sv.type = $type,
    sv.defaultValue = $defaultValue, sv.filePath = $filePath,
    sv.componentName = $componentName;
"""

MERGE_CONTEXT = """
MERGE (ctx:Context {uid: $uid})
ON CREATE SET ctx.name = $name, ctx.filePath = $filePath,
    ctx.defaultValue = $defaultValue, ctx.exportType = $exportType
ON MATCH SET ctx.name = $name, ctx.filePath = $filePath,
    ctx.defaultValue = $defaultValue, ctx.exportType = $exportType;
"""

MERGE_EVENT_HANDLER = """
MERGE (eh:EventHandler {uid: $uid})
ON CREATE SET
    eh.name = $name, eh.eventType = $eventType, eh.filePath = $filePath,
    eh.componentName = $componentName, eh.isInline = $isInline
ON MATCH SET
    eh.name = $name, eh.eventType = $eventType, eh.filePath = $filePath,
    eh.componentName = $componentName, eh.isInline = $isInline;
"""

# ──────────────────────────────────────────────────────
# Stage 3: Per-file relationship edges
# ──────────────────────────────────────────────────────

MERGE_DEFINED_IN_FC = """
MATCH (fc:Function_Component {uid: $compUid})
MATCH (f:File {filePath: $filePath})
MERGE (fc)-[:DEFINED_IN]->(f);
"""

MERGE_DEFINED_IN_CC = """
MATCH (cc:Class_Component {uid: $compUid})
MATCH (f:File {filePath: $filePath})
MERGE (cc)-[:DEFINED_IN]->(f);
"""

MERGE_DEFINED_IN_CUSTOM_HOOK = """
MATCH (ch:Custom_Hook {uid: $hookUid})
MATCH (f:File {filePath: $filePath})
MERGE (ch)-[:DEFINED_IN]->(f);
"""

MERGE_FC_USES_LIBRARY_HOOK = """
MATCH (fc:Function_Component {uid: $compUid})
MATCH (lh:Library_Hook {uid: $hookUid})
MERGE (fc)-[r:USES_LIBRARY_HOOK]->(lh)
SET r.count = $count;
"""

MERGE_FC_USES_CUSTOM_HOOK = """
MATCH (fc:Function_Component {uid: $compUid})
MATCH (ch:Custom_Hook {uid: $hookUid})
MERGE (fc)-[:USES_CUSTOM_HOOK]->(ch);
"""

MERGE_ACCEPTS_PROP = """
OPTIONAL MATCH (fc:Function_Component {uid: $compUid})
OPTIONAL MATCH (cc:Class_Component {uid: $compUid})
WITH coalesce(fc, cc) AS comp
MATCH (pr:Prop {uid: $propUid})
WHERE comp IS NOT NULL
MERGE (comp)-[:ACCEPTS_PROP]->(pr);
"""

MERGE_HAS_HANDLER = """
OPTIONAL MATCH (fc:Function_Component {uid: $compUid})
OPTIONAL MATCH (cc:Class_Component {uid: $compUid})
WITH coalesce(fc, cc) AS comp
MATCH (eh:EventHandler {uid: $ehUid})
WHERE comp IS NOT NULL
MERGE (comp)-[:HAS_HANDLER]->(eh);
"""

MERGE_DECLARES_STATE = """
MATCH (fc:Function_Component {uid: $sourceUid})
MATCH (sv:State_Variable {uid: $svUid})
MERGE (fc)-[r:DECLARES_STATE]->(sv)
SET r.init_is_literal = $initIsLiteral;
"""

MERGE_CUSTOM_HOOK_DECLARES_STATE = """
MATCH (ch:Custom_Hook {uid: $sourceUid})
MATCH (sv:State_Variable {uid: $svUid})
MERGE (ch)-[r:DECLARES_STATE]->(sv)
SET r.init_is_literal = $initIsLiteral;
"""

MERGE_DECLARES_CLASS_STATE = """
MATCH (cc:Class_Component {uid: $compUid})
MATCH (sv:State_Variable {uid: $svUid})
MERGE (cc)-[r:DECLARES_CLASS_STATE]->(sv)
SET r.declarationStyle = $declarationStyle;
"""

# ──────────────────────────────────────────────────────
# Stage 4: Cross-file edges
# ──────────────────────────────────────────────────────

MERGE_USES_COMPONENT = """
OPTIONAL MATCH (p1:Function_Component {uid: $parentUid})
OPTIONAL MATCH (p2:Class_Component {uid: $parentUid})
WITH coalesce(p1, p2) AS parent
OPTIONAL MATCH (c1:Function_Component {uid: $childUid})
OPTIONAL MATCH (c2:Class_Component {uid: $childUid})
WITH parent, coalesce(c1, c2) AS child
WHERE parent IS NOT NULL AND child IS NOT NULL
MERGE (parent)-[r:USES_COMPONENT]->(child)
SET r.usage = $usage;
"""

MERGE_PASSES_PROP = """
OPTIONAL MATCH (p1:Function_Component {uid: $parentUid})
OPTIONAL MATCH (p2:Class_Component {uid: $parentUid})
WITH coalesce(p1, p2) AS parent
OPTIONAL MATCH (c1:Function_Component {uid: $childUid})
OPTIONAL MATCH (c2:Class_Component {uid: $childUid})
WITH parent, coalesce(c1, c2) AS child
WHERE parent IS NOT NULL AND child IS NOT NULL
MERGE (parent)-[r:PASSES_PROP {propName: $propName}]->(child);
"""

MERGE_CUSTOM_HOOK_USES_LIBRARY_HOOK = """
MATCH (ch:Custom_Hook {uid: $hookUid})
MERGE (lh:Library_Hook {uid: $lhUid})
ON CREATE SET lh.name = $lhName, lh.source = $lhSource
MERGE (ch)-[r:USES_LIBRARY_HOOK]->(lh)
SET r.count = $count;
"""

MERGE_CUSTOM_HOOK_USES_CUSTOM_HOOK = """
MATCH (ch:Custom_Hook {uid: $sourceHookUid})
MATCH (target:Custom_Hook {uid: $targetHookUid})
MERGE (ch)-[:USES_CUSTOM_HOOK]->(target);
"""

MERGE_PROVIDES_CONTEXT = """
OPTIONAL MATCH (fc:Function_Component {uid: $compUid})
OPTIONAL MATCH (cc:Class_Component {uid: $compUid})
WITH coalesce(fc, cc) AS comp
MATCH (ctx:Context {uid: $ctxUid})
WHERE comp IS NOT NULL
MERGE (comp)-[r:PROVIDES_CONTEXT]->(ctx)
SET r.valueExpression = $valueExpression;
"""

MERGE_CONSUMES_CONTEXT_FC = """
MATCH (fc:Function_Component {uid: $consumerUid})
MATCH (ctx:Context {uid: $ctxUid})
MERGE (fc)-[:CONSUMES_CONTEXT]->(ctx);
"""

MERGE_CONSUMES_CONTEXT_CC = """
MATCH (cc:Class_Component {uid: $consumerUid})
MATCH (ctx:Context {uid: $ctxUid})
MERGE (cc)-[:CONSUMES_CONTEXT]->(ctx);
"""

MERGE_CONSUMES_CONTEXT_HOOK = """
MATCH (ch:Custom_Hook {uid: $consumerUid})
MATCH (ctx:Context {uid: $ctxUid})
MERGE (ch)-[:CONSUMES_CONTEXT]->(ctx);
"""

MERGE_ROUTES_TO = """
OPTIONAL MATCH (s1:Function_Component {uid: $sourceUid})
OPTIONAL MATCH (s2:Class_Component {uid: $sourceUid})
WITH coalesce(s1, s2) AS source
OPTIONAL MATCH (t1:Function_Component {uid: $targetUid})
OPTIONAL MATCH (t2:Class_Component {uid: $targetUid})
WITH source, coalesce(t1, t2) AS target
WHERE source IS NOT NULL AND target IS NOT NULL
MERGE (source)-[r:ROUTES_TO]->(target)
SET r.path = $path, r.isNested = $isNested,
    r.isLazy = $isLazy, r.isProtected = $isProtected;
"""

MERGE_PROVIDED_BY = """
MATCH (lh:Library_Hook)
MATCH (lib:Library {name: lh.source})
MERGE (lh)-[:PROVIDED_BY]->(lib);
"""

MERGE_RENDERS_ROOT_COMPONENT = """
MATCH (f:File {filePath: $entrypointPath})
OPTIONAL MATCH (fc:Function_Component {name: $rootComponentName})
OPTIONAL MATCH (cc:Class_Component {name: $rootComponentName})
WITH f, coalesce(fc, cc) AS comp
WHERE comp IS NOT NULL
MERGE (f)-[:RENDERS_ROOT_COMPONENT]->(comp);
"""

SET_IS_ROOT = """
OPTIONAL MATCH (fc:Function_Component {name: $rootComponentName})
OPTIONAL MATCH (cc:Class_Component {name: $rootComponentName})
WITH coalesce(fc, cc) AS comp
WHERE comp IS NOT NULL
SET comp.isRoot = true;
"""

SET_ALL_NOT_ROOT = """
MATCH (c)
WHERE (c:Function_Component OR c:Class_Component)
  AND c.name <> $rootComponentName
SET c.isRoot = false;
"""

# ──────────────────────────────────────────────────────
# Utility / Stats
# ──────────────────────────────────────────────────────

COUNT_NODES_BY_LABEL = """
MATCH (n)
WITH labels(n) AS lbls
UNWIND lbls AS label
RETURN label, count(*) AS count
ORDER BY count DESC;
"""

COUNT_RELATIONSHIPS = """
MATCH ()-[r]->()
RETURN type(r) AS type, count(*) AS count
ORDER BY count DESC;
"""

DUMP_DATABASE = "DUMP DATABASE;"
