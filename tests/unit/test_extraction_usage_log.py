"""Tests for Phase 1 extraction token-usage logging (IJCKG revision WP0)."""

from __future__ import annotations

import json
from pathlib import Path

import litellm
import pytest
from litellm import ModelResponse
from pydantic import BaseModel

from src.config import get_settings
from src.extraction import llm_extractor
from src.extraction.llm_extractor import PROMPTS, extract_file, extract_file_cross_file
from src.extraction.provenance import build_provenance
from src.llm import client
from src.llm.extraction_log import ExtractionRunLog, read_records, summarize
from src.graph.models import CompositionResponse


@pytest.fixture(autouse=True)
def _no_delay_no_cache(monkeypatch):
    """No 20 s extraction throttle, and a cache that always misses unless a test says otherwise."""
    monkeypatch.setattr(get_settings().llm, "call_delay", 0.0)
    monkeypatch.setattr(llm_extractor, "get_cached", lambda *a: None)
    monkeypatch.setattr(llm_extractor, "set_cached", lambda *a: None)


@pytest.fixture
def run_log(tmp_path: Path) -> ExtractionRunLog:
    return ExtractionRunLog("demo", "anthropic/test-model", log_dir=tmp_path, run_id="r1")


def _attempt(input_tokens: int, output_tokens: int) -> dict:
    return {
        "ok": True,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "rate_limit": None,
    }


def _fake_extract(attempts: list[dict], *, fail: Exception | None = None):
    """Stand-in for extract_structured that reports `attempts` into the usage sink."""

    async def fake(prompt, response_model, model=None, *, usage_sink=None):
        if usage_sink is not None:
            usage_sink.extend(attempts)
        if fail is not None:
            raise fail
        return response_model()

    return fake


# --------------------------------------------------------------------------- #
# Per-call records                                                            #
# --------------------------------------------------------------------------- #

async def test_billed_call_records_summed_usage_and_attempts(monkeypatch, run_log):
    """A validation re-ask is two billed attempts; both count."""
    monkeypatch.setattr(
        llm_extractor, "extract_structured", _fake_extract([_attempt(100, 10), _attempt(120, 15)])
    )

    await extract_file("src/App.jsx", "const App = () => null;", run_log=run_log)

    records = read_records(run_log.path)
    assert len(records) == len(PROMPTS)
    first = records[0]
    assert first["cache_hit"] is False
    assert first["attempts"] == 2
    assert first["usage"]["input_tokens"] == 220
    assert first["usage"]["output_tokens"] == 25
    assert first["call_purpose"] == "extraction_per_file"
    assert first["stage"] == "per_file"
    assert first["file_path"] == "src/App.jsx"
    assert first["error"] is None
    assert "prompt" not in first and "response" not in first


async def test_cache_hit_logged_with_zero_usage(monkeypatch, run_log):
    monkeypatch.setattr(llm_extractor, "get_cached", lambda *a: {"components": []})

    async def must_not_call(*a, **k):
        raise AssertionError("cache hit must not reach the API")

    monkeypatch.setattr(llm_extractor, "extract_structured", must_not_call)

    await extract_file("src/App.jsx", "x", run_log=run_log)

    records = read_records(run_log.path)
    assert len(records) == len(PROMPTS)
    assert all(r["cache_hit"] and r["attempts"] == 0 for r in records)
    assert all(r["usage"]["input_tokens"] == 0 for r in records)


async def test_failed_call_logged_before_empty_fallback(monkeypatch, run_log):
    """The failure is swallowed into an empty result, but its spend is not lost."""
    monkeypatch.setattr(
        llm_extractor,
        "extract_structured",
        _fake_extract([_attempt(90, 5)], fail=RuntimeError("validation exhausted")),
    )

    results = await extract_file("src/App.jsx", "x", run_log=run_log)

    assert results["function_components"] == {"components": []}
    record = read_records(run_log.path)[0]
    assert record["error"] == {"error_type": "RuntimeError", "message": "validation exhausted"}
    assert record["usage"]["input_tokens"] == 90


async def test_cross_file_call_logged_under_its_own_purpose(monkeypatch, run_log):
    monkeypatch.setattr(llm_extractor, "extract_structured", _fake_extract([_attempt(300, 40)]))

    await extract_file_cross_file(
        "src/App.jsx", "x", "composition", "composition_and_prop_flow.jinja2",
        CompositionResponse, run_log=run_log,
    )

    (record,) = read_records(run_log.path)
    assert record["stage"] == "cross_file"
    assert record["call_purpose"] == "extraction_cross_file"
    assert record["prompt_id"] == "composition"


async def test_without_run_log_nothing_is_written(monkeypatch, tmp_path):
    """run_log=None is the pre-WP0 behaviour: no sink passed, no file written."""
    seen: list = []

    async def fake(prompt, response_model, model=None, **kwargs):
        seen.append(kwargs)
        return response_model()

    monkeypatch.setattr(llm_extractor, "extract_structured", fake)

    await extract_file("src/App.jsx", "x")

    assert all(kw == {} for kw in seen)
    assert list(tmp_path.iterdir()) == []


# --------------------------------------------------------------------------- #
# Instructor re-ask accounting, through the real client code                  #
# --------------------------------------------------------------------------- #

class _Thing(BaseModel):
    count: int


def _tool_response(arguments: str, prompt_tokens: int, completion_tokens: int) -> ModelResponse:
    return ModelResponse(
        model="anthropic/test-model",
        choices=[{
            "index": 0,
            "finish_reason": "tool_calls",
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "_Thing", "arguments": arguments},
                }],
            },
        }],
        usage={
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    )


async def test_instructor_reask_counts_each_attempt_once(monkeypatch):
    """Instructor overwrites the final response's usage with a running total; the
    sink must still hold per-attempt figures, so nothing is double-counted."""
    responses = [
        _tool_response('{"count": "not a number"}', 100, 10),  # fails validation -> re-ask
        _tool_response('{"count": 3}', 130, 12),
    ]

    async def fake_acompletion(*args, **kwargs):
        return responses.pop(0)

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    sink: list[dict] = []
    result = await client.extract_structured("prompt", _Thing, usage_sink=sink)

    assert result.count == 3
    assert [(a["input_tokens"], a["output_tokens"]) for a in sink] == [(100, 10), (130, 12)]
    assert all(a["ok"] for a in sink)


# --------------------------------------------------------------------------- #
# Provenance summary                                                          #
# --------------------------------------------------------------------------- #

def test_summary_totals_equal_log_and_complete_run(run_log):
    run_log.record_call("per_file", "function_components", "a.jsx",
                        attempt_usage=[_attempt(100, 10), _attempt(110, 11)], latency_ms=1500)
    run_log.record_call("cross_file", "composition", "a.jsx",
                        attempt_usage=[_attempt(300, 30)], latency_ms=500,
                        error=RuntimeError("boom"))

    usage = summarize(run_log, call_delay_s=0.0, files_resumed_from_checkpoint=0,
                      wall_clock_s={"stage_2_3": 10.0, "stage_4": 2.0})

    records = read_records(run_log.path)
    assert usage["input_tokens"] == sum(r["usage"]["input_tokens"] for r in records) == 510
    assert usage["output_tokens"] == 51
    assert usage["calls_api"] == 2
    assert usage["api_attempts"] == 3
    assert usage["calls_failed"] == 1
    assert usage["api_latency_s"] == 2.0
    assert usage["complete"] is True
    assert usage["by_stage"]["per_file"]["input_tokens"] == 210
    assert usage["by_stage"]["cross_file"]["calls_failed"] == 1
    assert usage["by_prompt"]["composition"]["input_tokens"] == 300


def test_summary_incomplete_on_cache_hit(run_log):
    run_log.record_cache_hit("per_file", "contexts", "a.jsx")
    usage = summarize(run_log, call_delay_s=0.0, files_resumed_from_checkpoint=0,
                      wall_clock_s={})
    assert usage["complete"] is False
    assert usage["calls_cache_hit"] == 1


def test_summary_incomplete_on_resumed_files(run_log):
    run_log.record_call("per_file", "contexts", "a.jsx",
                        attempt_usage=[_attempt(1, 1)], latency_ms=1)
    usage = summarize(run_log, call_delay_s=0.0, files_resumed_from_checkpoint=3,
                      wall_clock_s={})
    assert usage["complete"] is False
    assert usage["files_resumed_from_checkpoint"] == 3


def test_provenance_usage_block_is_optional(tmp_path):
    kwargs = dict(repo_root=tmp_path, project_id="p", model="m", prompt_ids=["a"], file_count=1)
    assert "usage" not in build_provenance(**kwargs)
    assert build_provenance(**kwargs, usage={"complete": True})["usage"] == {"complete": True}
    json.dumps(build_provenance(**kwargs, usage={"complete": True}))
