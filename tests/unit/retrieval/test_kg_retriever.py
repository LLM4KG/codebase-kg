"""Tests for KGAugmentedRetriever (classifier + run_query mocked)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.retrieval.classifier import ClassifierResult
from src.retrieval.config import RetrievalConditionConfig
from src.retrieval.kg_retriever import KGAugmentedRetriever, build_generation_prompt


def _config() -> RetrievalConditionConfig:
    return RetrievalConditionConfig(
        condition_id="kg_augmented", retriever="kg_augmented", format_variant="A", max_rounds=1
    )


def _retriever() -> KGAugmentedRetriever:
    return KGAugmentedRetriever(
        _config(), model="anthropic/claude-sonnet-4-5", run_id="run1", project_name="rsc"
    )


async def test_bug_fix_dispatch_and_result(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "CartProduct.tsx").write_text("export const CartProduct = () => null;")

    row = {
        "componentName": "CartProduct", "filePath": "src/CartProduct.tsx",
        "componentType": "Function_Component",
        "acceptedProps": [{"name": None}], "libraryHooks": [{"name": None}],
        "customHooks": [{"name": None}], "stateVars": [{"name": None}],
        "classStateVars": [{"name": None}], "eventHandlers": [{"handlerName": None}],
        "directParents": [{"name": None}], "delegatedHooks": [{"name": None}],
    }
    run_query = MagicMock(return_value=[row])
    classify = AsyncMock(return_value=ClassifierResult(task_type="bug_fix", anchor_names=["CartProduct"]))

    with patch("src.retrieval.kg_retriever.run_query", run_query), \
         patch("src.retrieval.kg_retriever.classify_task", classify):
        result = await _retriever().retrieve("Fix CartProduct.", "react-shopping-cart", tmp_path)

    # bug_fix template dispatched with correctly-bound params.
    query_arg, params = run_query.call_args.args
    assert "BUG_FIX" in query_arg
    assert params == {
        "projectId": "react-shopping-cart",
        "anchorNames": ["CartProduct"],
        "anchorRoutes": [],
    }
    assert result.retriever_name == "kg_augmented"
    assert result.condition_id == "kg_augmented"
    assert len(result.rounds) == 1
    assert result.rounds[0].query == "bug_fix"
    assert "CartProduct" in result.context
    assert result.total_token_count > 0
    assert result.metadata["task_type"] == "bug_fix"
    assert result.metadata["anchor_names"] == ["CartProduct"]


async def test_feature_addition_runs_two_queries(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "NoteList.tsx").write_text("export const NoteList = () => null;")

    anchor_row = {
        "componentName": "NoteList", "filePath": "src/NoteList.tsx",
        "componentType": "Function_Component",
        "children": [{"name": None}], "acceptedProps": [{"name": None}],
        "libraryHooks": [{"name": None}], "customHooks": [{"name": None}],
        "stateVars": [{"name": None}], "consumedContexts": [{"name": None}],
        "childConsumedContexts": [{"name": None}],
    }
    routing_row = {
        "routerComponent": "App", "routerFile": "src/App.tsx", "routePath": "/app",
        "isNested": False, "isProtected": True, "isLazy": False,
        "targetComponent": "TakeNoteApp", "targetFile": "src/TakeNoteApp.tsx",
    }

    def fake_run_query(query, params):
        return [routing_row] if "ROUTES_TO" in query else [anchor_row]

    run_query = MagicMock(side_effect=fake_run_query)
    classify = AsyncMock(return_value=ClassifierResult(task_type="feature_addition", anchor_names=["NoteList"]))

    with patch("src.retrieval.kg_retriever.run_query", run_query), \
         patch("src.retrieval.kg_retriever.classify_task", classify):
        result = await _retriever().retrieve("Add route.", "takenote", tmp_path)

    assert run_query.call_count == 2  # Query A + Query B
    assert "Project routing table" in result.context
    assert "TakeNoteApp" in result.context


def test_build_generation_prompt_includes_context_and_spec():
    prompt = build_generation_prompt("Do the thing.", "### Target Components\nfoo")
    assert "Do the thing." in prompt
    assert "### Target Components" in prompt
    assert "unified diff" in prompt  # from generation_instruction.jinja2


def test_build_generation_prompt_floor_omits_empty_context():
    prompt = build_generation_prompt("Do the thing.", "")
    assert "Do the thing." in prompt
    assert "unified diff" in prompt
