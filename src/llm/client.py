"""Instructor + LiteLLM wrapper for structured LLM extraction."""

from __future__ import annotations

import asyncio
import logging
from typing import TypeVar

import instructor
import litellm
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from src.config import get_settings

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
) -> T:
    """
    Send a prompt to the LLM and get back a validated Pydantic model.

    Uses Instructor for automatic JSON validation and retry.
    Rate-limited via asyncio.Semaphore.
    """
    cfg = get_settings().llm
    model_name = model or cfg.model

    client = get_async_instructor_client()
    sem = _get_semaphore()

    async with sem:
        response = await client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            response_model=response_model,
            temperature=cfg.temperature,
            max_retries=cfg.max_retries,
        )

    return response


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
