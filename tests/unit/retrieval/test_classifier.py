"""Tests for the task classifier / anchor extractor."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.llm.logger import LLMResponse
from src.retrieval.classifier import (
    ClassifierResult,
    classify_task,
    parse_classifier_response,
)


def _resp(text: str) -> LLMResponse:
    return LLMResponse(text=text, usage=None, model_id="m", latency_ms=1.0)


def test_parse_valid_json():
    r = parse_classifier_response(
        '{"task_type": "bug_fix", "anchor_names": ["CartProduct"], "anchor_routes": []}'
    )
    assert r.task_type == "bug_fix"
    assert r.anchor_names == ["CartProduct"]
    assert r.anchor_routes == []


def test_parse_strips_markdown_fence():
    r = parse_classifier_response(
        '```json\n{"task_type": "refactoring", "anchor_names": ["NoteMenuBar"]}\n```'
    )
    assert r.task_type == "refactoring"
    assert r.anchor_names == ["NoteMenuBar"]


def test_parse_extracts_embedded_object():
    r = parse_classifier_response(
        'Sure! {"task_type": "feature_addition", "anchor_names": ["NoteList"], "anchor_routes": ["/app"]}'
    )
    assert r.task_type == "feature_addition"
    assert r.anchor_routes == ["/app"]


def test_parse_malformed_falls_back():
    r = parse_classifier_response("not json at all")
    assert isinstance(r, ClassifierResult)
    assert r.anchor_names == []
    assert r.task_type == "bug_fix"


def test_parse_invalid_task_type_falls_back():
    r = parse_classifier_response('{"task_type": "wat", "anchor_names": ["X"]}')
    assert r.task_type == "bug_fix"
    assert r.anchor_names == ["X"]  # anchors preserved even when type invalid


async def test_classify_task_passes_purpose_and_model():
    mock = AsyncMock(return_value=_resp('{"task_type": "bug_fix", "anchor_names": ["CartProduct"]}'))
    with patch("src.retrieval.classifier.logged_llm_call", mock):
        result = await classify_task(
            "Fix the CartProduct decrement bug.",
            model="anthropic/claude-sonnet-4-5",
            run_id="run1",
            condition_id="kg_augmented",
        )
    assert result.anchor_names == ["CartProduct"]
    kwargs = mock.call_args.kwargs
    assert kwargs["call_purpose"] == "classifier"
    assert kwargs["model"] == "anthropic/claude-sonnet-4-5"
    assert kwargs["run_id"] == "run1"
    assert kwargs["condition_id"] == "kg_augmented"
    # The rendered prompt must contain the spec.
    assert "CartProduct" in kwargs["messages"][0]["content"]
