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


# ─────────────────────────────────────────────────────────────────────────────
# Anchor resolution (WP8). "strict" is the published arm and must not move.
# ─────────────────────────────────────────────────────────────────────────────

def _hardened_config() -> RetrievalConditionConfig:
    return RetrievalConditionConfig(
        condition_id="kg_augmented_hardened", retriever="kg_augmented",
        format_variant="A", max_rounds=1,
        retriever_params={"anchor_resolution": "hardened"},
    )


_CART_ROW = {
    "componentName": "CartProduct", "filePath": "src/CartProduct.tsx",
    "componentType": "Function_Component",
    "acceptedProps": [{"name": None}], "libraryHooks": [{"name": None}],
    "customHooks": [{"name": None}], "stateVars": [{"name": None}],
    "classStateVars": [{"name": None}], "eventHandlers": [{"handlerName": None}],
    "directParents": [{"name": None}], "delegatedHooks": [{"name": None}],
}
_CANDIDATE_ROWS = [
    {"name": "CartProduct", "uid": "CartProduct::src/CartProduct.tsx",
     "filePath": "src/CartProduct.tsx", "label": "Function_Component"},
]


def _anchor_repo(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "CartProduct.tsx").write_text("export const CartProduct = () => null;")
    return tmp_path


def _router(anchor_rows, candidate_rows=_CANDIDATE_ROWS, overview_rows=()):
    """Route a mocked run_query by which template it was handed."""
    def fake(query, params):
        if "ANCHOR CANDIDATES" in query:
            return list(candidate_rows)
        if "PROJECT OVERVIEW" in query:
            return list(overview_rows)
        if "ROUTES_TO" in query:
            return []
        return list(anchor_rows)
    return MagicMock(side_effect=fake)


def test_unknown_anchor_resolution_mode_is_rejected():
    config = RetrievalConditionConfig(
        condition_id="broken", retriever="kg_augmented",
        retriever_params={"anchor_resolution": "lenient"},
    )
    with pytest.raises(ValueError, match="anchor_resolution"):
        KGAugmentedRetriever(config, model="m", run_id="r")


async def test_strict_is_the_default_and_adds_no_metadata(tmp_path):
    """Regression guard: the published arm's behaviour and metadata are unchanged."""
    run_query = _router([_CART_ROW])
    classify = AsyncMock(return_value=ClassifierResult(task_type="bug_fix", anchor_names=["CartProduct"]))
    with patch("src.retrieval.kg_retriever.run_query", run_query), \
         patch("src.retrieval.kg_retriever.classify_task", classify):
        retriever = _retriever()
        assert retriever.anchor_resolution == "strict"
        result = await retriever.retrieve("Fix it.", "rsc", _anchor_repo(tmp_path))

    assert set(result.metadata) == {"task_type", "anchor_names", "anchor_routes"}
    # No anchor_candidates query was run: strict never resolves.
    assert all("ANCHOR CANDIDATES" not in c.args[0] for c in run_query.call_args_list)


async def test_strict_empty_anchors_render_an_empty_context(tmp_path):
    """The latent bug, pinned: zero rows in, headers only out, and no warning anywhere."""
    run_query = _router([])
    classify = AsyncMock(return_value=ClassifierResult(task_type="bug_fix", anchor_names=[]))
    with patch("src.retrieval.kg_retriever.run_query", run_query), \
         patch("src.retrieval.kg_retriever.classify_task", classify):
        result = await _retriever().retrieve("Fix it.", "rsc", _anchor_repo(tmp_path))

    assert "CartProduct" not in result.context
    assert result.metadata.get("anchor_fallback") is None


async def test_hardened_repairs_a_misspelled_anchor(tmp_path):
    run_query = _router([_CART_ROW])
    classify = AsyncMock(return_value=ClassifierResult(task_type="bug_fix", anchor_names=["CartPorduct"]))
    with patch("src.retrieval.kg_retriever.run_query", run_query), \
         patch("src.retrieval.kg_retriever.classify_task", classify):
        retriever = KGAugmentedRetriever(
            _hardened_config(), model="m", run_id="r", project_name="rsc"
        )
        result = await retriever.retrieve("Fix it.", "rsc", _anchor_repo(tmp_path))

    # The corrected name is what reached $anchorNames…
    primary = [c for c in run_query.call_args_list if "BUG_FIX" in c.args[0]][0]
    assert primary.args[1]["anchorNames"] == ["CartProduct"]
    # …while the metadata keeps what the classifier actually said.
    assert result.metadata["anchor_names"] == ["CartPorduct"]
    assert result.metadata["anchor_names_dispatched"] == ["CartProduct"]
    assert result.metadata["anchor_resolutions"][0]["status"] == "fuzzy"
    assert result.metadata["anchor_fallback"] is False
    assert "CartProduct" in result.context


async def test_hardened_with_no_resolvable_anchor_falls_back_to_a_bounded_overview(tmp_path):
    overview = [
        {"componentName": f"Comp{i}", "filePath": f"src/Comp{i}.tsx",
         "componentType": "Function_Component", "propNames": ["a", "b"],
         "hookNames": ["useState"], "stateNames": ["x"], "weight": 4}
        for i in range(3)
    ]
    run_query = _router([], candidate_rows=[], overview_rows=overview)
    classify = AsyncMock(return_value=ClassifierResult(task_type="bug_fix", anchor_names=["Nope"]))
    with patch("src.retrieval.kg_retriever.run_query", run_query), \
         patch("src.retrieval.kg_retriever.classify_task", classify):
        retriever = KGAugmentedRetriever(
            _hardened_config(), model="m", run_id="r", project_name="rsc"
        )
        result = await retriever.retrieve("Fix it.", "rsc", _anchor_repo(tmp_path))

    assert result.metadata["anchor_fallback"] is True
    assert result.metadata["anchor_resolutions"][0]["status"] == "unresolved"
    assert result.total_token_count > 0
    assert "Comp0" in result.context and "Comp2" in result.context
    assert "not context scoped to the task" in result.context
    # The anchor-scoped template is never run when nothing resolved.
    assert all("BUG_FIX" not in c.args[0] for c in run_query.call_args_list)


async def test_hardened_overview_respects_the_token_budget(tmp_path):
    overview = [
        {"componentName": f"Comp{i}", "filePath": f"src/very/long/path/Comp{i}.tsx",
         "componentType": "Function_Component",
         "propNames": [f"prop{j}" for j in range(20)],
         "hookNames": ["useState", "useEffect"], "stateNames": ["x", "y"], "weight": 24}
        for i in range(40)
    ]
    run_query = _router([], candidate_rows=[], overview_rows=overview)
    classify = AsyncMock(return_value=ClassifierResult(task_type="bug_fix", anchor_names=[]))
    with patch("src.retrieval.kg_retriever.run_query", run_query), \
         patch("src.retrieval.kg_retriever.classify_task", classify):
        retriever = KGAugmentedRetriever(
            _hardened_config(), model="m", run_id="r", project_name="rsc", token_budget=200
        )
        result = await retriever.retrieve("Fix it.", "rsc", _anchor_repo(tmp_path))

    assert result.metadata["anchor_fallback"] is True
    assert result.total_token_count <= 400  # bounded, not the whole 40-row listing
    assert "Comp39" not in result.context


async def test_hardened_reports_a_route_the_graph_does_not_have(tmp_path):
    run_query = _router([_CART_ROW])
    classify = AsyncMock(return_value=ClassifierResult(
        task_type="bug_fix", anchor_names=["CartProduct"], anchor_routes=["/notes/trash"]
    ))
    with patch("src.retrieval.kg_retriever.run_query", run_query), \
         patch("src.retrieval.kg_retriever.classify_task", classify):
        retriever = KGAugmentedRetriever(
            _hardened_config(), model="m", run_id="r", project_name="rsc"
        )
        result = await retriever.retrieve("Fix it.", "rsc", _anchor_repo(tmp_path))

    assert result.metadata["anchor_routes_unknown"] == ["/notes/trash"]
