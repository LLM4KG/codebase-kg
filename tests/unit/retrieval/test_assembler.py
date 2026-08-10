"""Tests for the context assembler."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.retrieval.assembler import assemble_context

EMPTY = [{"name": None}]  # the all-null placeholder Cypher collect() emits


def _write(repo: Path, rel: str, content: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def _bug_fix_row() -> dict:
    return {
        "componentName": "CartProduct",
        "filePath": "src/CartProduct.tsx",
        "componentType": "Function_Component",
        "acceptedProps": [{"name": "product", "type": "ICartProduct", "isRequired": True}],
        "libraryHooks": [{"name": "useState", "source": "react"}],
        "customHooks": [{"name": "useCartProducts", "filePath": "src/useCartProducts.ts"}],
        "stateVars": [{"name": "qty", "type": "number", "defaultValue": "0"}],
        "classStateVars": EMPTY,
        "eventHandlers": [{"eventType": "click", "handlerName": "handleAdd"}],
        "directParents": [{"name": "CartProducts", "filePath": "src/CartProducts.tsx"}],
        "delegatedHooks": [{"name": "useCartProducts", "filePath": "src/useCartProducts.ts"}],
    }


def test_bug_fix_assembly(tmp_path):
    _write(tmp_path, "src/CartProduct.tsx", "export const CartProduct = () => null;")
    _write(tmp_path, "src/useCartProducts.ts", "export const useCartProducts = () => ({});")

    cd = assemble_context(
        task_spec="Fix the decrement bug.",
        task_type="bug_fix",
        rows=[_bug_fix_row()],
        repo_root=tmp_path,
        project_name="react-shopping-cart",
    )

    # Anchor + delegated hook are target components (with source).
    names = [c.name for c in cd.target_components]
    assert "CartProduct" in names and "useCartProducts" in names
    anchor = next(c for c in cd.target_components if c.name == "CartProduct")
    assert "CartProduct" in (anchor.source_code or "")
    assert [p["name"] for p in anchor.props] == ["product"]
    assert {h["name"] for h in anchor.hooks} == {"useState", "useCartProducts"}
    assert [s["name"] for s in anchor.state_variables] == ["qty"]

    # Direct parent is a metadata-only neighbor.
    assert [c.name for c in cd.neighbor_components] == ["CartProducts"]
    assert all(c.source_code is None for c in cd.neighbor_components)

    # Event handler note present.
    assert any("event handlers" in n and "handleAdd" in n for n in cd.cross_cutting_notes)


def test_missing_source_file_is_graceful(tmp_path):
    row = _bug_fix_row()
    # No files written -> source unreadable, must not crash.
    cd = assemble_context(
        task_spec="x",
        task_type="bug_fix",
        rows=[row],
        repo_root=tmp_path,
        project_name="p",
    )
    anchor = next(c for c in cd.target_components if c.name == "CartProduct")
    assert anchor.source_code is None


def test_feature_addition_routing_and_missing_route(tmp_path):
    _write(tmp_path, "src/NoteList.tsx", "export const NoteList = () => null;")
    rows = [{
        "componentName": "NoteList",
        "filePath": "src/NoteList.tsx",
        "componentType": "Function_Component",
        "children": [{"name": "SearchBar", "filePath": "src/SearchBar.tsx"}],
        "acceptedProps": EMPTY,
        "libraryHooks": EMPTY,
        "customHooks": EMPTY,
        "stateVars": EMPTY,
        "consumedContexts": EMPTY,
        "childConsumedContexts": EMPTY,
    }]
    routing_rows = [{
        "routerComponent": "App", "routerFile": "src/App.tsx",
        "routePath": "/app", "isNested": False, "isProtected": True, "isLazy": False,
        "targetComponent": "TakeNoteApp", "targetFile": "src/TakeNoteApp.tsx",
    }]

    cd = assemble_context(
        task_spec="Add a trashed-notes route.",
        task_type="feature_addition",
        rows=rows,
        repo_root=tmp_path,
        project_name="takenote",
        routing_rows=routing_rows,
        anchor_routes=["/notes/trash"],
    )
    notes = "\n".join(cd.cross_cutting_notes)
    assert "Project routing table:" in notes
    assert "/app" in notes and "TakeNoteApp" in notes
    assert "protected" in notes
    assert "/notes/trash" in notes and "not present" in notes
    assert [c.name for c in cd.neighbor_components] == ["SearchBar"]


def test_refactoring_caller_warning(tmp_path):
    _write(tmp_path, "src/NoteMenuBar.tsx", "export const NoteMenuBar = () => null;")
    rows = [{
        "componentName": "NoteMenuBar",
        "filePath": "src/NoteMenuBar.tsx",
        "componentType": "Function_Component",
        "acceptedProps": EMPTY,
        "callers": [{"name": "NoteEditor", "filePath": "src/NoteEditor.tsx", "uid": "NoteEditor::src/NoteEditor.tsx"}],
        "libraryHooks": [{"name": "useState", "source": "react"}],
        "customHooks": EMPTY,
        "stateVars": EMPTY,
        "classStateVars": EMPTY,
        "eventHandlers": EMPTY,
        "children": EMPTY,
    }]
    cd = assemble_context(
        task_spec="Extract a hook from NoteMenuBar.",
        task_type="refactoring",
        rows=rows,
        repo_root=tmp_path,
        project_name="takenote",
        caller_props={"NoteEditor::src/NoteEditor.tsx": ["note"]},
    )
    # Caller warning includes the caller name and its passed props (L3 split join).
    assert any(
        "Refactoring NoteMenuBar" in n and "NoteEditor" in n and "note" in n
        for n in cd.cross_cutting_notes
    )
    assert "NoteEditor" in [c.name for c in cd.neighbor_components]


def test_truncation_drops_neighbors_keeps_anchor_source(tmp_path):
    huge = "word " * 20000  # ~26k estimated tokens, far over budget
    _write(tmp_path, "src/CartProduct.tsx", huge)
    _write(tmp_path, "src/useCartProducts.ts", "hook source")

    cd = assemble_context(
        task_spec="Fix bug.",
        task_type="bug_fix",
        rows=[_bug_fix_row()],
        repo_root=tmp_path,
        project_name="p",
        token_budget=7000,
    )
    # Neighbors, secondary source, notes all dropped; anchor source survives.
    assert cd.neighbor_components == []
    assert [c.name for c in cd.target_components] == ["CartProduct"]
    assert len(cd.target_components[0].source_code or "") > 0
