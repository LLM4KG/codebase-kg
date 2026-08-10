"""Tests for the Phase 2 LLM call logger."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from litellm import ModelResponse

from src.llm.logger import (
    VALID_CALL_PURPOSES,
    LLMResponse,
    logged_llm_call,
    logged_llm_call_sync,
    _parse_model_provider,
    _extract_usage,
    _extract_openrouter_provider,
    _extract_rate_limit,
)

# --- Three provider model strings for parameterized tests ---

ALL_MODELS = [
    "claude-sonnet-4-20250514",
    "openrouter/qwen/qwen-2.5-coder-32b-instruct",
    "openrouter/deepseek/deepseek-chat-v3.1",
]

COMMON_KWARGS = dict(
    run_id="test_run",
    condition_id="kg_augmented",
    call_purpose="generator",
    temperature=0.0,
    max_tokens=512,
)


def _make_mock_response(model: str = "claude-sonnet-4-20250514", *, openrouter_provider: str | None = None):
    """Create a mock LiteLLM ModelResponse with usage info."""
    response = MagicMock(spec=ModelResponse)
    response.choices = [MagicMock()]
    response.choices[0].message.content = "mock response text"
    response.usage = MagicMock()
    response.usage.prompt_tokens = 150
    response.usage.completion_tokens = 50
    response.model = model

    hidden = {}
    if openrouter_provider:
        hidden["additional_headers"] = {"x-openrouter-provider": openrouter_provider}
    response._hidden_params = hidden
    return response


# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------


class TestParseModelProvider:
    def test_anthropic_direct(self):
        assert _parse_model_provider("claude-sonnet-4-20250514") == "anthropic"

    def test_anthropic_prefixed(self):
        assert _parse_model_provider("anthropic/claude-sonnet-4-20250514") == "anthropic"

    def test_openrouter(self):
        assert _parse_model_provider("openrouter/qwen/qwen-2.5-coder-32b-instruct") == "openrouter"

    def test_openrouter_deepseek(self):
        assert _parse_model_provider("openrouter/deepseek/deepseek-chat-v3.1") == "openrouter"


class TestExtractUsage:
    def test_extracts_tokens(self):
        resp = _make_mock_response()
        usage = _extract_usage(resp)
        assert usage == {"input_tokens": 150, "output_tokens": 50}

    def test_none_when_no_usage(self):
        resp = _make_mock_response()
        resp.usage = None
        assert _extract_usage(resp) is None


class TestExtractOpenrouterProvider:
    def test_extracts_provider(self):
        resp = _make_mock_response(openrouter_provider="Together")
        assert _extract_openrouter_provider(resp) == "Together"

    def test_none_when_absent(self):
        resp = _make_mock_response()
        assert _extract_openrouter_provider(resp) is None


# ---------------------------------------------------------------------------
# Async logged_llm_call tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model", ALL_MODELS)
async def test_schema_completeness(tmp_path: Path, model: str):
    """Every schema field is present and has the correct type."""
    mock_resp = _make_mock_response(model)

    with patch("src.llm.logger._acompletion_with_retry", new_callable=AsyncMock, return_value=mock_resp):
        result = await logged_llm_call(
            messages=[{"role": "user", "content": "hello"}],
            model=model,
            log_dir=tmp_path,
            **COMMON_KWARGS,
        )

    log_file = tmp_path / "test_run" / "kg_augmented.jsonl"
    assert log_file.exists()

    record = json.loads(log_file.read_text().strip())

    required_fields = {
        "timestamp": str,
        "model_id": str,
        "model_provider": str,
        "model_version": str,
        "params": dict,
        "prompt": list,
        "response": str,
        "usage": (dict, type(None)),
        "call_purpose": str,
        "latency_ms": float,
        "condition_id": str,
        "run_id": str,
        "openrouter_provider": (str, type(None)),
    }

    for field, expected_type in required_fields.items():
        assert field in record, f"Missing field: {field}"
        assert isinstance(record[field], expected_type), (
            f"Field {field}: expected {expected_type}, got {type(record[field])}"
        )

    assert isinstance(result, LLMResponse)
    assert result.text == "mock response text"
    assert result.model_id == model


@pytest.mark.parametrize("model", ALL_MODELS)
async def test_usage_field_captured(tmp_path: Path, model: str):
    """The logged record contains correct input/output token counts."""
    mock_resp = _make_mock_response(model)

    with patch("src.llm.logger._acompletion_with_retry", new_callable=AsyncMock, return_value=mock_resp):
        result = await logged_llm_call(
            messages=[{"role": "user", "content": "test"}],
            model=model,
            log_dir=tmp_path,
            **COMMON_KWARGS,
        )

    record = json.loads((tmp_path / "test_run" / "kg_augmented.jsonl").read_text().strip())
    assert record["usage"] == {"input_tokens": 150, "output_tokens": 50}
    assert result.usage == {"input_tokens": 150, "output_tokens": 50}


@pytest.mark.parametrize("purpose", sorted(VALID_CALL_PURPOSES))
async def test_call_purpose_captured(tmp_path: Path, purpose: str):
    """Each valid call_purpose is logged correctly."""
    mock_resp = _make_mock_response()

    with patch("src.llm.logger._acompletion_with_retry", new_callable=AsyncMock, return_value=mock_resp):
        await logged_llm_call(
            messages=[{"role": "user", "content": "test"}],
            model="claude-sonnet-4-20250514",
            run_id="test_run",
            condition_id="floor",
            call_purpose=purpose,
            log_dir=tmp_path,
        )

    record = json.loads((tmp_path / "test_run" / "floor.jsonl").read_text().strip())
    assert record["call_purpose"] == purpose


@pytest.mark.parametrize("invalid_purpose", ["summarizer", "", "GENERATOR", "classify"])
async def test_call_purpose_validation_rejects_invalid(tmp_path: Path, invalid_purpose: str):
    """ValueError is raised for invalid call_purpose values."""
    with pytest.raises(ValueError, match="Invalid call_purpose"):
        await logged_llm_call(
            messages=[{"role": "user", "content": "test"}],
            model="claude-sonnet-4-20250514",
            run_id="test_run",
            condition_id="floor",
            call_purpose=invalid_purpose,
            log_dir=tmp_path,
        )


async def test_write_before_return(tmp_path: Path):
    """The JSONL file exists and contains the record by the time the function returns."""
    mock_resp = _make_mock_response()

    with patch("src.llm.logger._acompletion_with_retry", new_callable=AsyncMock, return_value=mock_resp):
        result = await logged_llm_call(
            messages=[{"role": "user", "content": "test"}],
            model="claude-sonnet-4-20250514",
            log_dir=tmp_path,
            **COMMON_KWARGS,
        )

    log_file = tmp_path / "test_run" / "kg_augmented.jsonl"
    assert log_file.exists()
    content = log_file.read_text().strip()
    assert len(content) > 0
    record = json.loads(content)
    assert record["response"] == "mock response text"


async def test_file_organization(tmp_path: Path):
    """Log file is created at the expected path: {log_dir}/{run_id}/{condition_id}.jsonl."""
    mock_resp = _make_mock_response()

    with patch("src.llm.logger._acompletion_with_retry", new_callable=AsyncMock, return_value=mock_resp):
        await logged_llm_call(
            messages=[{"role": "user", "content": "test"}],
            model="claude-sonnet-4-20250514",
            run_id="my_run",
            condition_id="bm25",
            call_purpose="classifier",
            log_dir=tmp_path,
        )

    expected = tmp_path / "my_run" / "bm25.jsonl"
    assert expected.exists()
    assert expected.is_file()


async def test_append_behavior(tmp_path: Path):
    """Two calls produce two JSON lines in the same file."""
    mock_resp = _make_mock_response()

    with patch("src.llm.logger._acompletion_with_retry", new_callable=AsyncMock, return_value=mock_resp):
        await logged_llm_call(
            messages=[{"role": "user", "content": "first"}],
            model="claude-sonnet-4-20250514",
            log_dir=tmp_path,
            **COMMON_KWARGS,
        )
        await logged_llm_call(
            messages=[{"role": "user", "content": "second"}],
            model="claude-sonnet-4-20250514",
            log_dir=tmp_path,
            **COMMON_KWARGS,
        )

    log_file = tmp_path / "test_run" / "kg_augmented.jsonl"
    lines = [line for line in log_file.read_text().strip().split("\n") if line]
    assert len(lines) == 2

    record1 = json.loads(lines[0])
    record2 = json.loads(lines[1])
    assert record1["prompt"][0]["content"] == "first"
    assert record2["prompt"][0]["content"] == "second"


async def test_openrouter_provider_captured(tmp_path: Path):
    """OpenRouter provider header is captured for openrouter/ models."""
    mock_resp = _make_mock_response(
        "openrouter/qwen/qwen-2.5-coder-32b-instruct",
        openrouter_provider="Together",
    )

    with patch("src.llm.logger._acompletion_with_retry", new_callable=AsyncMock, return_value=mock_resp):
        await logged_llm_call(
            messages=[{"role": "user", "content": "test"}],
            model="openrouter/qwen/qwen-2.5-coder-32b-instruct",
            log_dir=tmp_path,
            **COMMON_KWARGS,
        )

    record = json.loads((tmp_path / "test_run" / "kg_augmented.jsonl").read_text().strip())
    assert record["openrouter_provider"] == "Together"


async def test_openrouter_provider_none_for_anthropic(tmp_path: Path):
    """openrouter_provider is None for direct Anthropic calls."""
    mock_resp = _make_mock_response()

    with patch("src.llm.logger._acompletion_with_retry", new_callable=AsyncMock, return_value=mock_resp):
        await logged_llm_call(
            messages=[{"role": "user", "content": "test"}],
            model="claude-sonnet-4-20250514",
            log_dir=tmp_path,
            **COMMON_KWARGS,
        )

    record = json.loads((tmp_path / "test_run" / "kg_augmented.jsonl").read_text().strip())
    assert record["openrouter_provider"] is None


async def test_latency_is_positive(tmp_path: Path):
    """latency_ms is a positive float in both the record and the return value."""
    mock_resp = _make_mock_response()

    with patch("src.llm.logger._acompletion_with_retry", new_callable=AsyncMock, return_value=mock_resp):
        result = await logged_llm_call(
            messages=[{"role": "user", "content": "test"}],
            model="claude-sonnet-4-20250514",
            log_dir=tmp_path,
            **COMMON_KWARGS,
        )

    record = json.loads((tmp_path / "test_run" / "kg_augmented.jsonl").read_text().strip())
    assert record["latency_ms"] >= 0
    assert result.latency_ms >= 0


async def test_params_include_extra(tmp_path: Path):
    """Extra parameters are included in the logged params dict."""
    mock_resp = _make_mock_response()

    with patch("src.llm.logger._acompletion_with_retry", new_callable=AsyncMock, return_value=mock_resp):
        await logged_llm_call(
            messages=[{"role": "user", "content": "test"}],
            model="claude-sonnet-4-20250514",
            log_dir=tmp_path,
            run_id="test_run",
            condition_id="kg_augmented",
            call_purpose="generator",
            temperature=0.0,
            max_tokens=512,
            top_p=0.9,
        )

    record = json.loads((tmp_path / "test_run" / "kg_augmented.jsonl").read_text().strip())
    assert record["params"]["top_p"] == 0.9
    assert record["params"]["temperature"] == 0.0
    assert record["params"]["max_tokens"] == 512


# ---------------------------------------------------------------------------
# Sync version tests
# ---------------------------------------------------------------------------


def test_sync_schema_completeness(tmp_path: Path):
    """Sync version logs a complete record with all schema fields."""
    mock_resp = _make_mock_response()

    with patch("src.llm.logger._completion_with_retry", return_value=mock_resp):
        result = logged_llm_call_sync(
            messages=[{"role": "user", "content": "hello sync"}],
            model="claude-sonnet-4-20250514",
            log_dir=tmp_path,
            **COMMON_KWARGS,
        )

    log_file = tmp_path / "test_run" / "kg_augmented.jsonl"
    assert log_file.exists()

    record = json.loads(log_file.read_text().strip())
    assert record["response"] == "mock response text"
    assert record["usage"] == {"input_tokens": 150, "output_tokens": 50}
    assert record["call_purpose"] == "generator"
    assert record["model_id"] == "claude-sonnet-4-20250514"
    assert isinstance(result, LLMResponse)
    assert result.text == "mock response text"


def test_sync_call_purpose_validation(tmp_path: Path):
    """Sync version also validates call_purpose."""
    with pytest.raises(ValueError, match="Invalid call_purpose"):
        logged_llm_call_sync(
            messages=[{"role": "user", "content": "test"}],
            model="claude-sonnet-4-20250514",
            run_id="test_run",
            condition_id="floor",
            call_purpose="invalid",
            log_dir=tmp_path,
        )


@pytest.mark.parametrize("model", ALL_MODELS)
def test_sync_all_providers(tmp_path: Path, model: str):
    """Sync version works across all three provider model strings."""
    mock_resp = _make_mock_response(model)

    with patch("src.llm.logger._completion_with_retry", return_value=mock_resp):
        result = logged_llm_call_sync(
            messages=[{"role": "user", "content": "test"}],
            model=model,
            log_dir=tmp_path,
            **COMMON_KWARGS,
        )

    record = json.loads((tmp_path / "test_run" / "kg_augmented.jsonl").read_text().strip())
    assert record["model_id"] == model
    assert record["usage"] == {"input_tokens": 150, "output_tokens": 50}
    assert result.model_id == model


# --------------------------------------------------------------------------- #
# Upstream provider failures (D-LLM2-qwen-amended)                            #
# --------------------------------------------------------------------------- #
# OpenRouter reports a backend that died mid-generation in-band, as
# `finish_reason: "error"`. LiteLLM cannot represent that finish_reason, so it
# raises a pydantic ValidationError and rewraps it as APIConnectionError — which
# this module otherwise retries three times before discarding the cause.

# Abridged from a real litellm.APIConnectionError observed against
# qwen/qwen-2.5-coder-32b-instruct on 2026-07-23.
REAL_UPSTREAM_ERROR_TEXT = (
    "litellm.APIConnectionError: APIConnectionError: OpenrouterException - "
    "Invalid response object Traceback (most recent call last):\n"
    "  ...\n"
    "pydantic_core._pydantic_core.ValidationError: 1 validation error for Choices\n"
    "finish_reason\n"
    "  Input should be 'stop', 'content_filter', ... [type=literal_error, "
    "input_value='error', input_type=str]\n"
    "received_args={'response_object': {'id': 'gen-123', 'model': "
    "'qwen/qwen-2.5-coder-32b-instruct', 'provider': 'Cloudflare', 'choices': "
    "[{'index': 0, 'finish_reason': 'error', 'error': {'code': 500, 'message': "
    "'Internal Server Error', 'metadata': {'error_type': 'server'}}, 'message': "
    "{'role': 'assistant', 'content': '```diff\\ndiff --git a/src/x.ts'}}]}}"
)


class TestUpstreamProviderError:
    def test_detects_and_extracts_payload(self):
        from src.llm.logger import _as_upstream_error

        exc = _as_upstream_error(
            Exception(REAL_UPSTREAM_ERROR_TEXT), "openrouter/qwen/qwen-2.5-coder-32b-instruct"
        )
        assert exc is not None
        assert exc.provider == "Cloudflare"
        assert exc.status_code == 500
        assert exc.upstream_message == "Internal Server Error"

    def test_ignores_genuine_connection_errors(self):
        """A real network failure must stay retryable, not be misclassified."""
        from src.llm.logger import _as_upstream_error

        assert _as_upstream_error(Exception("Connection reset by peer"), "m") is None

    def test_missing_fields_degrade_to_none(self):
        """Payload shape can drift; detection must not depend on every field."""
        from src.llm.logger import _as_upstream_error

        exc = _as_upstream_error(Exception("Invalid response object"), "m")
        assert exc is not None
        assert exc.provider is None and exc.status_code is None

    def test_not_retried(self, tmp_path):
        """The whole point: one attempt, not three, against a broken backend."""
        import litellm

        from src.llm.logger import UpstreamProviderError

        calls = []

        async def _boom(**kwargs):
            calls.append(1)
            raise litellm.APIConnectionError(
                message=REAL_UPSTREAM_ERROR_TEXT, llm_provider="openrouter", model="m"
            )

        with patch("litellm.acompletion", new=_boom):
            with pytest.raises(UpstreamProviderError) as info:
                asyncio.run(
                    logged_llm_call(
                        messages=[{"role": "user", "content": "hi"}],
                        model="openrouter/qwen/qwen-2.5-coder-32b-instruct",
                        log_dir=tmp_path,
                        **COMMON_KWARGS,
                    )
                )

        assert len(calls) == 1, f"expected a single attempt, got {len(calls)}"
        assert info.value.provider == "Cloudflare"

    def test_failure_is_written_to_jsonl(self, tmp_path):
        """A failed call must leave a trace, not a silent gap in the log."""
        import litellm

        from src.llm.logger import UpstreamProviderError

        async def _boom(**kwargs):
            raise litellm.APIConnectionError(
                message=REAL_UPSTREAM_ERROR_TEXT, llm_provider="openrouter", model="m"
            )

        with patch("litellm.acompletion", new=_boom):
            with pytest.raises(UpstreamProviderError):
                asyncio.run(
                    logged_llm_call(
                        messages=[{"role": "user", "content": "hi"}],
                        model="openrouter/qwen/qwen-2.5-coder-32b-instruct",
                        log_dir=tmp_path,
                        **COMMON_KWARGS,
                    )
                )

        record = json.loads((tmp_path / "test_run" / "kg_augmented.jsonl").read_text().strip())
        assert record["error"]["error_type"] == "upstream_provider_error"
        assert record["error"]["status_code"] == 500
        assert record["openrouter_provider"] == "Cloudflare"
        # Must be skippable by token/call-count consumers.
        assert record["usage"] is None and record["response"] == ""


class TestFailureDetail:
    def test_unwraps_tenacity_retry_error(self):
        """RetryError otherwise reports only the Future, discarding the cause."""
        from tenacity import RetryError

        from src.generation.orchestrator import _failure_detail
        from src.llm.logger import UpstreamProviderError

        cause = UpstreamProviderError(
            model="m", provider="Cloudflare", status_code=500,
            message="Internal Server Error", raw="raw payload",
        )
        attempt = MagicMock()
        attempt.failed = True
        attempt.exception.return_value = cause

        detail = _failure_detail(RetryError(attempt))
        assert "Cloudflare" in detail and "500" in detail and "raw payload" in detail

    def test_plain_exception(self):
        from src.generation.orchestrator import _failure_detail

        assert _failure_detail(ValueError("boom")) == "ValueError: boom"


class TestOpenRouterProviderExtraction:
    """OpenRouter reroutes the same model between backends; which one served a
    call is reproducibility data. The body carries it; LiteLLM does not surface
    the header, which is why the previous header-only lookup always returned None.
    """

    def test_reads_provider_from_response_body(self):
        response = MagicMock(spec=ModelResponse)
        response.provider = "WandB"
        assert _extract_openrouter_provider(response) == "WandB"

    def test_ignores_cdn_server_header(self):
        """`llm_provider-server` is the CDN in front of OpenRouter, not the
        inference backend — and it collides with a real provider name."""
        response = MagicMock(spec=ModelResponse)
        response.provider = None
        response._hidden_params = {
            "additional_headers": {"llm_provider-server": "cloudflare"}
        }
        assert _extract_openrouter_provider(response) is None

    def test_falls_back_to_header_when_body_absent(self):
        response = MagicMock(spec=ModelResponse)
        response.provider = None
        response._hidden_params = {"additional_headers": {"x-provider-name": "Together"}}
        assert _extract_openrouter_provider(response) == "Together"

    def test_non_string_body_value_rejected(self):
        """A MagicMock/sentinel `provider` attribute must not be logged as a name."""
        response = MagicMock(spec=ModelResponse)
        response._hidden_params = {}
        assert _extract_openrouter_provider(response) is None


class TestRateLimitExtraction:
    """Provider rate-limit headers, logged so Phase 5 headroom is observed rather
    than inferred. The pilot legs recorded none, so the only thing the gate review
    could say was that no limit was *hit* — which says nothing about how close it came.
    """

    @staticmethod
    def _with_headers(headers: dict):
        response = MagicMock(spec=ModelResponse)
        response._hidden_params = {"additional_headers": headers}
        return response

    def test_anthropic_three_limiters(self):
        rl = _extract_rate_limit(self._with_headers({
            "anthropic-ratelimit-requests-limit": "50",
            "anthropic-ratelimit-requests-remaining": "49",
            "anthropic-ratelimit-input-tokens-limit": "30000",
            "anthropic-ratelimit-input-tokens-remaining": "24500",
            "anthropic-ratelimit-output-tokens-limit": "8000",
            "anthropic-ratelimit-output-tokens-remaining": "7900",
        }))
        assert rl == {
            "requests_limit": 50,
            "requests_remaining": 49,
            "input_tokens_limit": 30000,
            "input_tokens_remaining": 24500,
            "output_tokens_limit": 8000,
            "output_tokens_remaining": 7900,
        }

    def test_litellm_provider_prefix(self):
        """LiteLLM re-emits provider headers under an `llm_provider-` prefix."""
        rl = _extract_rate_limit(self._with_headers({
            "llm_provider-anthropic-ratelimit-input-tokens-limit": "450000",
        }))
        assert rl == {"input_tokens_limit": 450000}

    def test_openrouter_combined_limiter(self):
        rl = _extract_rate_limit(self._with_headers({
            "x-ratelimit-limit": "200",
            "x-ratelimit-remaining": "199",
        }))
        assert rl == {"requests_limit": 200, "requests_remaining": 199}

    def test_reset_timestamp_stays_a_string(self):
        """Counts are numeric; resets are ISO-8601 and must not be coerced."""
        rl = _extract_rate_limit(self._with_headers({
            "anthropic-ratelimit-requests-reset": "2026-07-30T12:00:00Z",
        }))
        assert rl == {"requests_reset": "2026-07-30T12:00:00Z"}

    def test_none_when_provider_sends_nothing(self):
        """No recognised header must yield None, not an empty dict — records for
        providers without rate-limit reporting stay clean."""
        assert _extract_rate_limit(self._with_headers({})) is None
        assert _extract_rate_limit(self._with_headers({"content-type": "application/json"})) is None

    def test_reads_headers_off_an_exception(self):
        """A 429 is exactly when these headers matter, and LiteLLM hangs them off
        `exc.response.headers` rather than `_hidden_params`."""
        exc = Exception("rate limited")
        exc.response = MagicMock()
        exc.response.headers = {"retry-after": "12"}
        assert _extract_rate_limit(exc) == {"retry_after": 12}

    def test_logged_record_carries_the_block(self, tmp_path):
        response = _make_mock_response()
        response._hidden_params = {
            "additional_headers": {"anthropic-ratelimit-input-tokens-remaining": "24500"}
        }
        with patch("litellm.acompletion", new=AsyncMock(return_value=response)):
            asyncio.run(
                logged_llm_call(
                    messages=[{"role": "user", "content": "hi"}],
                    model="claude-sonnet-4-20250514",
                    log_dir=tmp_path,
                    **COMMON_KWARGS,
                )
            )
        record = json.loads((tmp_path / "test_run" / "kg_augmented.jsonl").read_text())
        assert record["rate_limit"] == {"input_tokens_remaining": 24500}


class TestPhase2CallDelay:
    """Phase 2 throttle. A SEPARATE key from llm.call_delay on purpose: that one is
    20.0 for extraction, and routing it here would silently slow every Phase 2 run.
    """

    def test_defaults_to_unthrottled(self):
        from src.config import get_settings

        assert get_settings().llm.phase2_call_delay == 0.0

    def test_no_sleep_when_zero(self, tmp_path):
        slept = []
        with patch("litellm.acompletion", new=AsyncMock(return_value=_make_mock_response())), \
             patch("asyncio.sleep", new=AsyncMock(side_effect=lambda d: slept.append(d))):
            asyncio.run(
                logged_llm_call(
                    messages=[{"role": "user", "content": "hi"}],
                    model="claude-sonnet-4-20250514",
                    log_dir=tmp_path,
                    call_delay=0.0,
                    **COMMON_KWARGS,
                )
            )
        assert slept == []

    def test_sleeps_when_configured(self, tmp_path):
        slept = []
        with patch("litellm.acompletion", new=AsyncMock(return_value=_make_mock_response())), \
             patch("asyncio.sleep", new=AsyncMock(side_effect=lambda d: slept.append(d))):
            asyncio.run(
                logged_llm_call(
                    messages=[{"role": "user", "content": "hi"}],
                    model="claude-sonnet-4-20250514",
                    log_dir=tmp_path,
                    call_delay=7.5,
                    **COMMON_KWARGS,
                )
            )
        assert slept == [7.5]

    def test_throttle_excluded_from_logged_latency(self, tmp_path):
        """The sleep is our own pacing, not provider latency."""
        with patch("litellm.acompletion", new=AsyncMock(return_value=_make_mock_response())), \
             patch("asyncio.sleep", new=AsyncMock()):
            result = asyncio.run(
                logged_llm_call(
                    messages=[{"role": "user", "content": "hi"}],
                    model="claude-sonnet-4-20250514",
                    log_dir=tmp_path,
                    call_delay=30.0,
                    **COMMON_KWARGS,
                )
            )
        record = json.loads((tmp_path / "test_run" / "kg_augmented.jsonl").read_text().strip())
        assert record["latency_ms"] < 1000, "throttle leaked into latency_ms"
        assert result.latency_ms < 1000

    def test_no_throttle_on_failure(self, tmp_path):
        """A failing call must raise immediately, not after the throttle."""
        import litellm

        slept = []
        async def _boom(**kwargs):
            raise litellm.APIConnectionError(
                message=REAL_UPSTREAM_ERROR_TEXT, llm_provider="openrouter", model="m"
            )

        from src.llm.logger import UpstreamProviderError

        with patch("litellm.acompletion", new=_boom), \
             patch("asyncio.sleep", new=AsyncMock(side_effect=lambda d: slept.append(d))):
            with pytest.raises(UpstreamProviderError):
                asyncio.run(
                    logged_llm_call(
                        messages=[{"role": "user", "content": "hi"}],
                        model="openrouter/qwen/qwen3-coder",
                        log_dir=tmp_path,
                        call_delay=30.0,
                        **COMMON_KWARGS,
                    )
                )
        assert slept == []
