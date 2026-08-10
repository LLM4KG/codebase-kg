"""Load a project's KG into Memgraph, honouring the one-project-per-DB constraint.

The two pilot dumps (react-shopping-cart, takenote) cannot co-reside in a single
Memgraph DB — the global `Library(name)` unique constraint collides (see CLAUDE.md
"Known limitation" and cypher_templates.md §11). The orchestrator groups candidates
by project and calls `ensure_project_kg_loaded()` before a project's kg_augmented
candidates run: it wipes the DB and imports that project's dump when a *different*
project is currently loaded.

Only the `kg_augmented` condition needs a KG; `floor` never touches Memgraph.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from src.graph.connection import run_query, run_query_void
from src.graph.schema import ensure_schema

logger = logging.getLogger(__name__)

GRAPH_EXPORT_DIR = Path("graph_export")


def resolve_project_id(project_name: str) -> str:
    """Return the KG's own projectId hash for a friendly project name.

    The retriever binds `$projectId` to this hash, not the friendly name. Queries
    the live DB first; falls back to graph_export/<name>/project.json offline.
    """
    try:
        rows = run_query(
            "MATCH (p:Project {name: $name}) RETURN p.projectId AS projectId",
            {"name": project_name},
        )
        if rows and rows[0].get("projectId"):
            return rows[0]["projectId"]
    except Exception as exc:  # DB down / unreachable — try the offline fallback.
        logger.debug("Live projectId lookup failed for %s: %s", project_name, exc)

    project_json = GRAPH_EXPORT_DIR / project_name / "project.json"
    if project_json.exists():
        data = json.loads(project_json.read_text(encoding="utf-8"))
        pid = data.get("projectId")
        if pid:
            return pid

    raise RuntimeError(f"Could not resolve projectId for project {project_name!r}")


def import_cypherl(dump_path: Path) -> tuple[int, int]:
    """Import a CYPHERL dump line-by-line. Returns (statements_ok, errors).

    Tolerates per-line errors (e.g. `CREATE CONSTRAINT` for an already-present
    constraint after a data-only wipe) exactly like `src/cli.py:import_graph`.
    """
    ensure_schema()
    count = 0
    errors = 0
    with open(dump_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                run_query_void(line)
                count += 1
            except Exception as exc:
                errors += 1
                if errors <= 5:
                    logger.warning("Import error: %s", exc)
    return count, errors


def _current_project_name() -> str | None:
    rows = run_query("MATCH (p:Project) RETURN p.name AS name LIMIT 1")
    return rows[0].get("name") if rows else None


def wipe_database() -> None:
    """Delete all nodes/edges (keeps constraints). Light — no container restart."""
    run_query_void("MATCH (n) DETACH DELETE n")


def ensure_project_kg_loaded(project_name: str) -> str:
    """Ensure `project_name`'s KG is the one loaded in Memgraph; return its projectId.

    No-op if it is already loaded. Otherwise wipes the DB and imports the dump.
    """
    current = _current_project_name()
    if current == project_name:
        logger.info("KG for %r already loaded", project_name)
        return resolve_project_id(project_name)

    if current is not None:
        logger.info("Wiping DB (currently loaded: %r)", current)
        wipe_database()

    dump = GRAPH_EXPORT_DIR / project_name / "full_dump.cypherl"
    if not dump.exists():
        raise FileNotFoundError(f"KG dump not found: {dump}")

    logger.info("Importing KG dump for %r …", project_name)
    count, errors = import_cypherl(dump)
    logger.info(
        "Imported %d statements (%d tolerated errors) for %r", count, errors, project_name
    )
    return resolve_project_id(project_name)
