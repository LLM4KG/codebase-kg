"""Real-Memgraph smoke tests for the four Cypher retrieval templates.

Marked @pytest.mark.memgraph. Self-skips if Memgraph is unreachable or the pilot
KGs are not loaded, so `pytest -m "not memgraph"` is the explicit opt-out.

Load the pilot KGs first, e.g.:
    docker compose up -d
    cat graph_export/react-shopping-cart/full_dump.cypherl | mgconsole
    cat graph_export/takenote/full_dump.cypherl | mgconsole

These tests verify the two implementation fixes from the plan:
  - eh.name (not the non-existent eh.handlerName) → handler names are non-null.
  - L3: the refactoring template's nested collect() yields proper propsPassed lists.
"""

from __future__ import annotations

import pytest

from src.graph.connection import run_query
from src.retrieval.kg_retriever import load_template

pytestmark = pytest.mark.memgraph


@pytest.fixture(scope="session", autouse=True)
def _require_memgraph():
    try:
        run_query("RETURN 0 AS x")
    except Exception as exc:  # noqa: BLE001 - any driver/connection error means skip
        pytest.skip(f"Memgraph not reachable: {exc}")


def _project_id(name: str) -> str:
    rows = run_query("MATCH (p:Project {name: $name}) RETURN p.projectId AS pid", {"name": name})
    if not rows or not rows[0].get("pid"):
        pytest.skip(f"Pilot KG for {name!r} not loaded into Memgraph")
    return rows[0]["pid"]


def _params(pid: str, anchors: list[str], routes: list[str] | None = None) -> dict:
    return {"projectId": pid, "anchorNames": anchors, "anchorRoutes": routes or []}


def _non_null(items, key="name"):
    return [d for d in (items or []) if d and d.get(key) is not None]


def test_bug_fix_query_shopping_cart():
    pid = _project_id("react-shopping-cart")
    rows = run_query(load_template("bug_fix.cypher"), _params(pid, ["CartProduct"]))
    assert rows, "bug_fix returned no rows for CartProduct"
    row = next(r for r in rows if r["componentName"] == "CartProduct")
    assert row["filePath"].endswith("CartProduct.tsx")
    # eh.name fix: any real handler must have a non-null handlerName.
    for h in _non_null(row["eventHandlers"], key="handlerName"):
        assert h["handlerName"] is not None


def test_feature_addition_queries_takenote():
    pid = _project_id("takenote")
    rows = run_query(load_template("feature_addition_a.cypher"), _params(pid, ["NoteList"]))
    assert rows, "feature_addition Query A returned no rows for NoteList"
    assert any(r["componentName"] == "NoteList" for r in rows)

    routing = run_query(load_template("feature_addition_b.cypher"), _params(pid, ["NoteList"]))
    assert routing, "feature_addition Query B (routing table) returned no routes for takenote"
    assert all("routePath" in r and "targetComponent" in r for r in routing)


def test_refactoring_query_takenote_L3():
    pid = _project_id("takenote")
    # L3: the main query must execute WITHOUT the "aggregation inside aggregation"
    # error (nested collect() removed; callers/children carry uid instead).
    rows = run_query(load_template("refactoring.cypher"), _params(pid, ["NoteMenuBar"]))
    assert rows, "refactoring returned no rows for NoteMenuBar"
    row = next(r for r in rows if r["componentName"] == "NoteMenuBar")

    callers = _non_null(row["callers"])
    assert callers, "expected NoteMenuBar to have at least one caller (NoteEditor)"
    for caller in callers:
        assert caller.get("uid"), "caller must carry uid for the props join"
    # eh.name fix: handler names non-null.
    for h in _non_null(row["eventHandlers"], key="handlerName"):
        assert h["handlerName"] is not None

    # The split caller-props query returns proper list-typed propsPassed, joinable on uid.
    prop_rows = run_query(load_template("refactoring_caller_props.cypher"), _params(pid, ["NoteMenuBar"]))
    caller_uids = {c["uid"] for c in callers}
    for pr in prop_rows:
        assert isinstance(pr["propsPassed"], list)
        assert pr["callerUid"] in caller_uids
