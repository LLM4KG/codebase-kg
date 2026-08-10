"""Tests for the floor (no-context) retriever."""

from __future__ import annotations

import pytest

from src.retrieval.config import RetrievalConditionConfig
from src.retrieval.floor_retriever import FloorRetriever


async def test_floor_returns_empty_context(tmp_path):
    config = RetrievalConditionConfig(condition_id="floor", retriever="floor")
    retriever = FloorRetriever(config)

    result = await retriever.retrieve(
        spec="Fix the bug.",
        project_id="react-shopping-cart",
        repo_root=tmp_path,
    )
    assert result.context == ""
    assert result.rounds == []
    assert result.retriever_name == "floor"
    assert result.condition_id == "floor"
    assert result.total_token_count == 0
