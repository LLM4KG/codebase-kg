"""Memgraph DDL: constraint and index creation."""

from __future__ import annotations

import logging

from src.graph.connection import run_query_void

logger = logging.getLogger(__name__)

# Constraints (Memgraph syntax)
CONSTRAINTS = [
    "CREATE CONSTRAINT ON (p:Project) ASSERT p.projectId IS UNIQUE;",
    "CREATE CONSTRAINT ON (f:File) ASSERT f.filePath IS UNIQUE;",
    "CREATE CONSTRAINT ON (fc:Function_Component) ASSERT fc.uid IS UNIQUE;",
    "CREATE CONSTRAINT ON (cc:Class_Component) ASSERT cc.uid IS UNIQUE;",
    "CREATE CONSTRAINT ON (lh:Library_Hook) ASSERT lh.uid IS UNIQUE;",
    "CREATE CONSTRAINT ON (ch:Custom_Hook) ASSERT ch.uid IS UNIQUE;",
    "CREATE CONSTRAINT ON (pr:Prop) ASSERT pr.uid IS UNIQUE;",
    "CREATE CONSTRAINT ON (sv:State_Variable) ASSERT sv.uid IS UNIQUE;",
    "CREATE CONSTRAINT ON (ctx:Context) ASSERT ctx.uid IS UNIQUE;",
    "CREATE CONSTRAINT ON (eh:EventHandler) ASSERT eh.uid IS UNIQUE;",
    "CREATE CONSTRAINT ON (lib:Library) ASSERT lib.name IS UNIQUE;",
]

# Indexes (Memgraph: constraint does NOT auto-create index)
INDEXES = [
    "CREATE INDEX ON :Project(projectId);",
    "CREATE INDEX ON :File(filePath);",
    "CREATE INDEX ON :Function_Component(uid);",
    "CREATE INDEX ON :Function_Component(name);",
    "CREATE INDEX ON :Class_Component(uid);",
    "CREATE INDEX ON :Class_Component(name);",
    "CREATE INDEX ON :Library_Hook(uid);",
    "CREATE INDEX ON :Custom_Hook(uid);",
    "CREATE INDEX ON :Prop(uid);",
    "CREATE INDEX ON :State_Variable(uid);",
    "CREATE INDEX ON :Context(uid);",
    "CREATE INDEX ON :EventHandler(uid);",
    "CREATE INDEX ON :Library(name);",
]


def ensure_schema() -> None:
    """Create all constraints and indexes (idempotent)."""
    for stmt in CONSTRAINTS:
        try:
            run_query_void(stmt)
        except Exception as e:
            if "already exists" in str(e).lower():
                pass
            else:
                logger.warning("Constraint creation warning: %s", e)

    for stmt in INDEXES:
        try:
            run_query_void(stmt)
        except Exception as e:
            if "already exists" in str(e).lower():
                pass
            else:
                logger.warning("Index creation warning: %s", e)

    logger.info("Schema constraints and indexes ensured")


def drop_all() -> None:
    """Drop all data from the graph (for testing / re-runs)."""
    run_query_void("MATCH (n) DETACH DELETE n;")
    logger.info("All graph data dropped")


def analyze_graph() -> None:
    """Run ANALYZE GRAPH to optimize query planning after bulk load."""
    try:
        run_query_void("ANALYZE GRAPH;")
        logger.info("ANALYZE GRAPH completed")
    except Exception as e:
        logger.warning("ANALYZE GRAPH failed (may not be supported): %s", e)
