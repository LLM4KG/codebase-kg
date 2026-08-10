"""Diskcache layer for LLM responses, keyed on (file_hash, prompt_id, model)."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import diskcache

from src.config import get_settings

logger = logging.getLogger(__name__)

_cache: diskcache.Cache | None = None


def get_cache() -> diskcache.Cache:
    global _cache
    if _cache is None:
        cache_dir = get_settings().pipeline.cache_dir
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
        _cache = diskcache.Cache(cache_dir)
    return _cache


def _make_key(file_content: str, prompt_id: str, model: str) -> str:
    """Create a cache key from file content hash + prompt ID + model."""
    content_hash = hashlib.sha256(file_content.encode()).hexdigest()[:16]
    return f"{content_hash}::{prompt_id}::{model}"


def get_cached(file_content: str, prompt_id: str, model: str) -> dict | None:
    """Retrieve a cached LLM response, or None if not cached."""
    cache = get_cache()
    key = _make_key(file_content, prompt_id, model)
    result = cache.get(key)
    if result is not None:
        logger.debug("Cache hit: %s", key)
        return json.loads(result) if isinstance(result, str) else result
    return None


def set_cached(file_content: str, prompt_id: str, model: str, response: dict) -> None:
    """Store an LLM response in the cache."""
    cache = get_cache()
    key = _make_key(file_content, prompt_id, model)
    cache.set(key, json.dumps(response))
    logger.debug("Cache set: %s", key)


def clear_cache() -> None:
    """Clear all cached entries."""
    cache = get_cache()
    cache.clear()
    logger.info("LLM cache cleared")
