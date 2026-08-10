"""Structured experiment logger for Phase 2 LLM calls.

Records every LLM call to disk as JSONL before returning the response.
Uses raw LiteLLM (not Instructor) — Phase 2 calls don't all need
Pydantic-validated structured output.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import litellm
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from src.config import get_settings

logger = logging.getLogger(__name__)

VALID_CALL_PURPOSES = frozenset({
    "classifier",
    "anchor_extractor",
    "reformulator",
    "generator",
})

_semaphore: asyncio.Semaphore | None = None


# --------------------------------------------------------------------------- #
# Upstream provider failures                                                  #
# --------------------------------------------------------------------------- #
# An OpenRouter backend can accept a request, start generating, then die with its
# own 5xx. OpenRouter reports that in-band as `finish_reason: "error"` plus an
# `error` object on the choice. LiteLLM's `Choices` model does not accept that
# finish_reason, so it raises a pydantic ValidationError and rewraps it as
# `APIConnectionError` — a type this module retries. The result: three futile
# retries against the same broken backend, then a bare `RetryError` whose message
# discards the provider name and status code.
#
# We detect that specific shape, extract the payload, and raise a distinct
# non-retryable error instead. See decision log D-LLM2-qwen-amended.

_UPSTREAM_MARKERS = ("Invalid response object", "'finish_reason': 'error'")
_RE_PROVIDER = re.compile(r"'provider':\s*'([^']+)'")
_RE_ERROR_OBJ = re.compile(r"'error':\s*\{'code':\s*(\d+),\s*'message':\s*'([^']*)'")


class UpstreamProviderError(RuntimeError):
    """A model backend accepted the request then failed mid-generation.

    Not retryable here: the failure is the backend's, and OpenRouter pins a model
    to its provider set, so an immediate retry hits the same one. Carries the
    provider/status so the cause reaches disk instead of being flattened into an
    opaque connection error.
    """

    def __init__(
        self,
        *,
        model: str,
        provider: str | None,
        status_code: int | None,
        message: str | None,
        raw: str,
    ) -> None:
        self.model = model
        self.provider = provider
        self.status_code = status_code
        self.upstream_message = message
        self.raw = raw
        super().__init__(
            f"upstream provider failure for {model!r} "
            f"(provider={provider or 'unknown'}, status={status_code or 'unknown'}): "
            f"{message or 'no message'}. The backend began generating and then errored; "
            f"retrying the same model will not help."
        )

    def as_dict(self) -> dict:
        return {
            "error_type": "upstream_provider_error",
            "model": self.model,
            "provider": self.provider,
            "status_code": self.status_code,
            "message": self.upstream_message,
        }


def _as_upstream_error(exc: Exception, model: str) -> UpstreamProviderError | None:
    """Return an UpstreamProviderError if `exc` is a rewrapped in-band provider failure."""
    text = str(exc)
    if not any(marker in text for marker in _UPSTREAM_MARKERS):
        return None
    provider_match = _RE_PROVIDER.search(text)
    error_match = _RE_ERROR_OBJ.search(text)
    return UpstreamProviderError(
        model=model,
        provider=provider_match.group(1) if provider_match else None,
        status_code=int(error_match.group(1)) if error_match else None,
        message=error_match.group(2) if error_match else None,
        raw=text[:4000],
    )


def _get_semaphore(concurrency: int | None = None) -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        limit = concurrency or get_settings().llm.concurrency
        _semaphore = asyncio.Semaphore(limit)
    return _semaphore


@dataclass
class LLMResponse:
    text: str
    usage: dict | None
    model_id: str
    latency_ms: float


def _parse_model_provider(model: str) -> str:
    """Extract the provider name from a LiteLLM model string."""
    if model.startswith("openrouter/"):
        return "openrouter"
    if model.startswith("anthropic/") or model.startswith("claude"):
        return "anthropic"
    parts = model.split("/", 1)
    return parts[0] if len(parts) > 1 else "anthropic"


def _extract_usage(response: Any) -> dict | None:
    """Extract token usage from a LiteLLM ModelResponse."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    prompt_tokens = getattr(usage, "prompt_tokens", None)
    completion_tokens = getattr(usage, "completion_tokens", None)
    if prompt_tokens is None and completion_tokens is None:
        return None
    return {
        "input_tokens": prompt_tokens,
        "output_tokens": completion_tokens,
    }


def _response_headers(obj: Any) -> dict:
    """Return the upstream HTTP response headers LiteLLM stashed on a response.

    LiteLLM parks them under `_hidden_params`, sometimes as `additional_headers`
    and sometimes as `headers`, and prefixes provider headers with
    `llm_provider-`. Callers should look up both the bare and prefixed spelling.

    Also accepts an *exception*: a 429 is precisely when the rate-limit headers
    are worth having, and LiteLLM hangs those off `exc.response.headers` rather
    than `_hidden_params`.
    """
    hidden = getattr(obj, "_hidden_params", None)
    if isinstance(hidden, dict):
        headers = hidden.get("additional_headers") or hidden.get("headers") or {}
        if isinstance(headers, dict) and headers:
            return headers

    nested = getattr(getattr(obj, "response", None), "headers", None)
    if isinstance(nested, dict):
        return nested
    # httpx.Headers is Mapping-like but not a dict.
    try:
        return dict(nested) if nested is not None else {}
    except (TypeError, ValueError):
        return {}


# Provider header suffix -> the key it becomes in the logged `rate_limit` block.
# Anthropic reports three independent limiters (requests, input tokens, output
# tokens); OpenRouter reports one combined request limiter. Whichever the
# provider sends is what gets logged — absent limiters are simply omitted.
_RATE_LIMIT_HEADERS = {
    "anthropic-ratelimit-requests-limit": "requests_limit",
    "anthropic-ratelimit-requests-remaining": "requests_remaining",
    "anthropic-ratelimit-requests-reset": "requests_reset",
    "anthropic-ratelimit-input-tokens-limit": "input_tokens_limit",
    "anthropic-ratelimit-input-tokens-remaining": "input_tokens_remaining",
    "anthropic-ratelimit-input-tokens-reset": "input_tokens_reset",
    "anthropic-ratelimit-output-tokens-limit": "output_tokens_limit",
    "anthropic-ratelimit-output-tokens-remaining": "output_tokens_remaining",
    "anthropic-ratelimit-output-tokens-reset": "output_tokens_reset",
    "anthropic-ratelimit-tokens-limit": "tokens_limit",
    "anthropic-ratelimit-tokens-remaining": "tokens_remaining",
    "x-ratelimit-limit": "requests_limit",
    "x-ratelimit-remaining": "requests_remaining",
    "x-ratelimit-reset": "requests_reset",
    "retry-after": "retry_after",
}


def _extract_rate_limit(response: Any) -> dict | None:
    """Capture the provider's rate-limit headers so headroom is observed, not inferred.

    Sizing `llm.phase2_call_delay` for Phase 5 (~4,200 generations) needs the
    account's real ceilings, and the pilot legs recorded none of them — the
    2026-07-23 gate review could only note that no limit was *hit*, which says
    nothing about how close it came. Logging the headers per call turns that into
    a query.

    Returns None when the provider sends no recognised header, so records for
    providers without rate-limit reporting stay clean.
    """
    headers = _response_headers(response)
    if not headers:
        return None

    lowered = {str(k).lower(): v for k, v in headers.items()}
    out: dict[str, Any] = {}
    for header, key in _RATE_LIMIT_HEADERS.items():
        value = lowered.get(header)
        if value is None:
            value = lowered.get(f"llm_provider-{header}")
        if value is None or value == "":
            continue
        # Counts arrive as strings; resets are ISO-8601 timestamps. Keep numbers
        # numeric so a reader can compare them without re-parsing.
        try:
            out[key] = int(value)
        except (TypeError, ValueError):
            out[key] = value

    return out or None


def _extract_openrouter_provider(response: Any) -> str | None:
    """Identify which upstream backend OpenRouter actually served a call from.

    OpenRouter silently routes the same model to different providers between
    calls (observed: Cloudflare and WandB for the same model), and backend health
    varies — so this is reproducibility data, not a detail.

    The response *body* carries `provider` and is the reliable source; LiteLLM
    does not surface `X-OpenRouter-Provider` in `_hidden_params`, which is why
    the header-only lookup this replaces always returned None. Headers are kept
    as a fallback in case that changes.

    Do NOT read `llm_provider-server` — that is the CDN in front of OpenRouter
    (always "cloudflare"), not the inference backend, and coincidentally
    collides with a real provider name.
    """
    body_provider = getattr(response, "provider", None)
    if isinstance(body_provider, str) and body_provider:
        return body_provider

    headers = _response_headers(response)
    if not headers:
        return None
    for key in (
        "x-openrouter-provider",
        "X-OpenRouter-Provider",
        "x-provider-name",
        "llm_provider-x-provider-name",
    ):
        value = headers.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _extract_response_text(response: Any) -> str:
    """Extract the text content from a LiteLLM ModelResponse."""
    try:
        return response.choices[0].message.content or ""
    except (AttributeError, IndexError):
        return ""


def _build_log_record(
    *,
    messages: list[dict],
    model: str,
    run_id: str,
    condition_id: str,
    call_purpose: str,
    params: dict,
    response: Any,
    latency_ms: float,
) -> dict:
    """Build the JSONL log record from call inputs and API response."""
    model_provider = _parse_model_provider(model)
    model_version = getattr(response, "model", None) or model

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model_id": model,
        "model_provider": model_provider,
        "model_version": model_version,
        "params": params,
        "prompt": messages,
        "response": _extract_response_text(response),
        "usage": _extract_usage(response),
        "call_purpose": call_purpose,
        "latency_ms": latency_ms,
        "condition_id": condition_id,
        "run_id": run_id,
        "openrouter_provider": _extract_openrouter_provider(response)
        if model_provider == "openrouter"
        else None,
        "rate_limit": _extract_rate_limit(response),
    }


def _build_error_record(
    *,
    messages: list[dict],
    model: str,
    run_id: str,
    condition_id: str,
    call_purpose: str,
    params: dict,
    exc: Exception,
    latency_ms: float,
) -> dict:
    """Build a JSONL record for a call that never produced a response.

    Same shape as a success record so one reader handles both, with `response`
    empty, `usage` null, and a populated `error` object. **Consumers computing
    token totals or call counts must skip records where `error` is not null** —
    they represent spend without output.
    """
    detail = (
        exc.as_dict()
        if isinstance(exc, UpstreamProviderError)
        else {"error_type": type(exc).__name__, "message": str(exc)[:2000]}
    )
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model_id": model,
        "model_provider": _parse_model_provider(model),
        "model_version": model,
        "params": params,
        "prompt": messages,
        "response": "",
        "usage": None,
        "call_purpose": call_purpose,
        "latency_ms": latency_ms,
        "condition_id": condition_id,
        "run_id": run_id,
        "openrouter_provider": detail.get("provider"),
        # A 429 carries the headers that explain it; other failures carry none.
        "rate_limit": _extract_rate_limit(exc),
        "error": detail,
    }


def _get_log_dir() -> Path:
    """Return the root experiment log directory."""
    return Path(
        getattr(get_settings().pipeline, "experiment_log_dir", "experiment_logs")
    )


def _write_log_record(record: dict, run_id: str, condition_id: str, log_dir: Path | None = None) -> None:
    """Append a JSON record to the appropriate JSONL file and flush."""
    root = log_dir or _get_log_dir()
    run_dir = root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log_file = run_dir / f"{condition_id}.jsonl"

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        f.flush()


def _validate_call_purpose(call_purpose: str) -> None:
    if call_purpose not in VALID_CALL_PURPOSES:
        raise ValueError(
            f"Invalid call_purpose {call_purpose!r}. "
            f"Must be one of: {', '.join(sorted(VALID_CALL_PURPOSES))}"
        )


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=10, max=90),
    retry=retry_if_exception_type((litellm.RateLimitError, litellm.APIConnectionError)),
    before_sleep=lambda retry_state: logger.warning(
        "Retrying LLM call (attempt %d): %s",
        retry_state.attempt_number,
        retry_state.outcome.exception() if retry_state.outcome else "unknown",
    ),
)
async def _acompletion_with_retry(*, model: str, messages: list[dict], **kwargs: Any) -> Any:
    try:
        return await litellm.acompletion(model=model, messages=messages, **kwargs)
    except litellm.APIConnectionError as exc:
        upstream = _as_upstream_error(exc, model)
        if upstream is None:
            raise  # a genuine connection problem — let tenacity retry it
        raise upstream from exc


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=10, max=90),
    retry=retry_if_exception_type((litellm.RateLimitError, litellm.APIConnectionError)),
    before_sleep=lambda retry_state: logger.warning(
        "Retrying LLM call (attempt %d): %s",
        retry_state.attempt_number,
        retry_state.outcome.exception() if retry_state.outcome else "unknown",
    ),
)
def _completion_with_retry(*, model: str, messages: list[dict], **kwargs: Any) -> Any:
    try:
        return litellm.completion(model=model, messages=messages, **kwargs)
    except litellm.APIConnectionError as exc:
        upstream = _as_upstream_error(exc, model)
        if upstream is None:
            raise  # a genuine connection problem — let tenacity retry it
        raise upstream from exc


async def logged_llm_call(
    messages: list[dict],
    model: str,
    run_id: str,
    condition_id: str,
    call_purpose: str,
    temperature: float = 0.0,
    max_tokens: int = 4096,
    log_dir: Path | None = None,
    concurrency: int | None = None,
    call_delay: float | None = None,
    **extra_params: Any,
) -> LLMResponse:
    """Make an async LLM call via LiteLLM and log the full record to JSONL.

    The JSONL record is flushed to disk BEFORE this function returns.

    `call_delay` (seconds) throttles successive calls; defaults to
    `llm.phase2_call_delay`, which is 0.0 — Phase 2 runs unthrottled unless
    configured otherwise. The sleep is excluded from the logged `latency_ms`.
    """
    _validate_call_purpose(call_purpose)

    params = {"temperature": temperature, "max_tokens": max_tokens, **extra_params}
    sem = _get_semaphore(concurrency)

    delay = get_settings().llm.phase2_call_delay if call_delay is None else call_delay

    start = time.perf_counter()
    try:
        async with sem:
            response = await _acompletion_with_retry(
                model=model, messages=messages, **params
            )
            # Measure before sleeping — the throttle is our own pacing, not
            # provider latency, and must not be folded into the logged metric.
            latency_ms = (time.perf_counter() - start) * 1000
            # Space successive calls while still holding the slot, so the gap is
            # per-slot rather than global. Only on success: an error is raised
            # immediately, since delaying a failure helps nothing.
            if delay > 0:
                await asyncio.sleep(delay)
    except Exception as exc:
        # Log the failure before re-raising — otherwise a failed call leaves no
        # trace at all and the cause has to be reconstructed from a stack trace.
        _write_log_record(
            _build_error_record(
                messages=messages,
                model=model,
                run_id=run_id,
                condition_id=condition_id,
                call_purpose=call_purpose,
                params=params,
                exc=exc,
                latency_ms=(time.perf_counter() - start) * 1000,
            ),
            run_id,
            condition_id,
            log_dir=log_dir,
        )
        raise

    record = _build_log_record(
        messages=messages,
        model=model,
        run_id=run_id,
        condition_id=condition_id,
        call_purpose=call_purpose,
        params=params,
        response=response,
        latency_ms=latency_ms,
    )

    _write_log_record(record, run_id, condition_id, log_dir=log_dir)

    return LLMResponse(
        text=_extract_response_text(response),
        usage=_extract_usage(response),
        model_id=model,
        latency_ms=latency_ms,
    )


def logged_llm_call_sync(
    messages: list[dict],
    model: str,
    run_id: str,
    condition_id: str,
    call_purpose: str,
    temperature: float = 0.0,
    max_tokens: int = 4096,
    log_dir: Path | None = None,
    call_delay: float | None = None,
    **extra_params: Any,
) -> LLMResponse:
    """Synchronous version of logged_llm_call (same `call_delay` semantics)."""
    _validate_call_purpose(call_purpose)

    params = {"temperature": temperature, "max_tokens": max_tokens, **extra_params}
    delay = get_settings().llm.phase2_call_delay if call_delay is None else call_delay

    start = time.perf_counter()
    response = _completion_with_retry(model=model, messages=messages, **params)
    latency_ms = (time.perf_counter() - start) * 1000  # excludes the throttle below
    if delay > 0:
        time.sleep(delay)

    record = _build_log_record(
        messages=messages,
        model=model,
        run_id=run_id,
        condition_id=condition_id,
        call_purpose=call_purpose,
        params=params,
        response=response,
        latency_ms=latency_ms,
    )

    _write_log_record(record, run_id, condition_id, log_dir=log_dir)

    return LLMResponse(
        text=_extract_response_text(response),
        usage=_extract_usage(response),
        model_id=model,
        latency_ms=latency_ms,
    )
