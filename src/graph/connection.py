"""Neo4j driver singleton for Memgraph (Bolt protocol)."""

from __future__ import annotations

from neo4j import GraphDatabase, Driver

from src.config import get_settings

_driver: Driver | None = None


def get_driver() -> Driver:
    """Return a singleton neo4j Driver connected to Memgraph."""
    global _driver
    if _driver is None:
        cfg = get_settings().db
        _driver = GraphDatabase.driver(
            cfg.uri,
            auth=(cfg.user, cfg.password) if cfg.user else None,
        )
    return _driver


def close_driver() -> None:
    """Close the driver and release connection pool resources."""
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None


def run_query(query: str, parameters: dict | None = None) -> list[dict]:
    """Execute a Cypher query and return results as a list of dicts."""
    driver = get_driver()
    with driver.session() as session:
        result = session.run(query, parameters or {})
        return [record.data() for record in result]


def run_query_void(query: str, parameters: dict | None = None) -> None:
    """Execute a Cypher query that returns no results."""
    driver = get_driver()
    with driver.session() as session:
        session.run(query, parameters or {})
