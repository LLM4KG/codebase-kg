"""Instructor + LiteLLM wrapper for structured LLM extraction."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, TypeVar

import instructor
import litellm
from instructor.core.hooks import Hooks
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from src.config import get_settings
from src.llm.logger import _extract_rate_limit

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Global semaphore for rate limiting
_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        cfg = get_settings().llm
        _semaphore = asyncio.Semaphore(cfg.concurrency)
    return _semaphore


def get_instructor_client() -> instructor.Instructor:
    """Create an Instructor client wrapping LiteLLM."""
    return instructor.from_litellm(litellm.completion)


def get_async_instructor_client() -> instructor.AsyncInstructor:
    """Create an async Instructor client wrapping LiteLLM."""
    return instructor.from_litellm(litellm.acompletion)


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
async def extract_structured(
    prompt: str,
    response_model: type[T],
    model: str | None = None,
    *,
    usage_sink: list[dict] | None = None,
) -> T:
    """
    Send a prompt to the LLM and get back a validated Pydantic model.

    Uses Instructor for automatic JSON validation and retry.
    Rate-limited via asyncio.Semaphore.

    `usage_sink`, when given, receives one entry per API attempt (see
    `_attempt_hooks`). One logical call can be several billed attempts: Instructor
    re-asks on a validation failure, and the tenacity decorator above re-runs the
    whole call on a rate limit or connection error. The same list is passed to
    every re-run, so it ends up holding every attempt's spend.
    """
    cfg = get_settings().llm
    model_name = model or cfg.model

    client = get_async_instructor_client()
    sem = _get_semaphore()

    kwargs: dict[str, Any] = {}
    if usage_sink is not None:
        kwargs["hooks"] = _attempt_hooks(usage_sink)

    async with sem:
        response = await client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            response_model=response_model,
            temperature=cfg.temperature,
            max_retries=cfg.max_retries,
            **kwargs,
        )

    return response


def _usage_of(raw_response: Any) -> dict:
    """Token usage of ONE raw API response.

    Read in the `completion:response` hook, which Instructor fires *before*
    `update_total_usage` overwrites the response's usage with the running total
    across re-asks. Reading usage off the final response instead would count
    every earlier attempt twice.
    """
    usage = getattr(raw_response, "usage", None)

    def _int(name: str) -> int:
        value = getattr(usage, name, None)
        return value if isinstance(value, int) else 0

    return {
        "input_tokens": _int("prompt_tokens"),
        "output_tokens": _int("completion_tokens"),
        "cache_read_input_tokens": _int("cache_read_input_tokens"),
        "cache_creation_input_tokens": _int("cache_creation_input_tokens"),
    }


def _attempt_hooks(usage_sink: list[dict]) -> Hooks:
    """Per-call Instructor hooks that append one entry per API attempt to `usage_sink`.

    Per call, not per client, so concurrent calls cannot see each other's attempts.
    A failed attempt (API error) has no response and so no usage; it is recorded
    with zero tokens, because the provider bills nothing for a rejected request.
    """
    hooks = Hooks()
    hooks.on("completion:response", lambda response: usage_sink.append({
        "ok": True,
        **_usage_of(response),
        "rate_limit": _extract_rate_limit(response),
    }))
    hooks.on("completion:error", lambda error: usage_sink.append({
        "ok": False,
        "error_type": type(error).__name__,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }))
    return hooks


def extract_structured_sync(
    prompt: str,
    response_model: type[T],
    model: str | None = None,
) -> T:
    """Synchronous version of extract_structured."""
    cfg = get_settings().llm
    model_name = model or cfg.model

    client = get_instructor_client()

    response = client.chat.completions.create(
        model=model_name,
        messages=[{"role": "user", "content": prompt}],
        response_model=response_model,
        temperature=cfg.temperature,
        max_retries=cfg.max_retries,
    )

    return response
