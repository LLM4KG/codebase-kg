"""Stage 2: Per-file LLM extraction — 7 prompts per file."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from src.config import get_settings
from src.llm.client import extract_structured
from src.llm.cache import get_cached, set_cached
from src.llm.extraction_log import ExtractionRunLog
from src.llm.prompt_loader import render_prompt
from src.graph.models import (
    FunctionComponentResponse,
    CustomHookResponse,
    ClassComponentResponse,
    PropAndHandlerResponse,
    LibraryUsageResponse,
    FunctionStateResponse,
    ClassStateResponse,
    ContextResponse,
    CompositionResponse,
    CustomHookInternalResponse,
    ContextProviderConsumerResponse,
    RouteDefinitionResponse,
)

logger = logging.getLogger(__name__)

# Per-file prompts (Stage 2)
#
# `custom_hooks` is a NEW prompt_id, deliberately not folded into
# function_component.jinja2. The LLM cache key is (file_content_hash, prompt_id,
# model) and excludes template contents (src/llm/cache.py), so editing an existing
# template in place silently returns responses cached from the old prompt. A new
# prompt_id also keeps the existing cache valid.
PROMPTS = [
    ("function_components", "function_component.jinja2", FunctionComponentResponse),
    ("custom_hooks", "custom_hook.jinja2", CustomHookResponse),
    ("class_components", "class_component.jinja2", ClassComponentResponse),
    ("props_and_handlers", "prop_and_event_handler.jinja2", PropAndHandlerResponse),
    ("library_usage", "library_usage.jinja2", LibraryUsageResponse),
    ("state_function", "state_variable_function.jinja2", FunctionStateResponse),
    ("state_class", "state_variable_class.jinja2", ClassStateResponse),
    ("contexts", "context.jinja2", ContextResponse),
]

# Cross-file prompts (Stage 4)
CROSS_FILE_PROMPTS = [
    ("composition", "composition_and_prop_flow.jinja2", CompositionResponse),
    ("custom_hook_internal", "custom_hook_internal.jinja2", CustomHookInternalResponse),
    ("context_provider_consumer", "context_provider_consumer.jinja2", ContextProviderConsumerResponse),
    ("route_definitions", "route_definition.jinja2", RouteDefinitionResponse),
]


async def _logged_extract(
    prompt_text: str,
    response_model: type,
    run_log: ExtractionRunLog | None,
    stage: str,
    prompt_id: str,
    file_path: str,
):
    """`extract_structured`, plus one usage record when a run log is attached.

    Only the API await is timed — the `call_delay` sleep that follows a success is
    our own pacing, not provider latency. A failure is recorded before it
    propagates, because the caller swallows it into an empty result and a failed
    call still cost whatever its attempts consumed.
    """
    if run_log is None:
        return await extract_structured(prompt_text, response_model)

    attempt_usage: list[dict] = []
    start = time.perf_counter()
    try:
        response = await extract_structured(
            prompt_text, response_model, usage_sink=attempt_usage
        )
    except BaseException as exc:
        run_log.record_call(
            stage, prompt_id, file_path,
            attempt_usage=attempt_usage,
            latency_ms=(time.perf_counter() - start) * 1000,
            error=exc,
        )
        raise
    run_log.record_call(
        stage, prompt_id, file_path,
        attempt_usage=attempt_usage,
        latency_ms=(time.perf_counter() - start) * 1000,
    )
    return response


async def extract_file(
    file_path: str, code: str, run_log: ExtractionRunLog | None = None
) -> dict:
    """
    Run all 7 per-file LLM prompts for a single source file.

    Returns a dict with keys matching the prompt IDs.
    """
    model = get_settings().llm.model
    results = {}

    for prompt_id, template, response_model in PROMPTS:
        # Check cache first
        cached = get_cached(code, prompt_id, model)
        if cached is not None:
            results[prompt_id] = cached
            logger.debug("Cache hit for %s/%s", file_path, prompt_id)
            if run_log is not None:
                run_log.record_cache_hit("per_file", prompt_id, file_path)
            continue

        # Render prompt and call LLM
        prompt_text = render_prompt(template, code=code)

        try:
            response = await _logged_extract(
                prompt_text, response_model, run_log, "per_file", prompt_id, file_path
            )
            result_dict = response.model_dump(by_alias=True)
            results[prompt_id] = result_dict
            set_cached(code, prompt_id, model, result_dict)
            logger.debug("Extracted %s for %s", prompt_id, file_path)
            delay = get_settings().llm.call_delay
            if delay > 0:
                await asyncio.sleep(delay)
        except Exception as e:
            logger.error("Failed to extract %s for %s: %s", prompt_id, file_path, e)
            results[prompt_id] = _empty_result(prompt_id)

    return results


async def extract_file_cross_file(file_path: str, code: str, prompt_id: str,
                                   template: str, response_model: type,
                                   run_log: ExtractionRunLog | None = None) -> dict:
    """Run a single cross-file LLM prompt for a source file."""
    model = get_settings().llm.model

    cached = get_cached(code, prompt_id, model)
    if cached is not None:
        if run_log is not None:
            run_log.record_cache_hit("cross_file", prompt_id, file_path)
        return cached

    prompt_text = render_prompt(template, code=code)

    try:
        response = await _logged_extract(
            prompt_text, response_model, run_log, "cross_file", prompt_id, file_path
        )
        result_dict = response.model_dump(by_alias=True)
        set_cached(code, prompt_id, model, result_dict)
        delay = get_settings().llm.call_delay
        if delay > 0:
            await asyncio.sleep(delay)
        return result_dict
    except Exception as e:
        logger.error("Failed cross-file extraction %s for %s: %s", prompt_id, file_path, e)
        return {}


async def extract_all_files(
    repo_root: Path,
    file_paths: list[str],
    on_progress: callable | None = None,
) -> dict[str, dict]:
    """
    Run LLM extraction on all files concurrently.

    Returns: {file_path: {prompt_id: result_dict}}
    """
    all_results: dict[str, dict] = {}

    tasks = []
    for fp in file_paths:
        full_path = repo_root / fp
        if not full_path.exists():
            logger.warning("File not found: %s", full_path)
            continue
        code = full_path.read_text(errors="replace")
        tasks.append((fp, code))

    for i, (fp, code) in enumerate(tasks):
        result = await extract_file(fp, code)
        all_results[fp] = result
        if on_progress:
            on_progress(i + 1, len(tasks), fp)

    return all_results


def _empty_result(prompt_id: str) -> dict:
    """Return an empty result dict for a failed prompt."""
    empty_map = {
        "function_components": {"components": []},
        "class_components": {"classComponents": []},
        "props_and_handlers": {"props": [], "eventHandlers": []},
        "library_usage": {"imports": []},
        "state_function": {"stateVariables": []},
        "state_class": {"classStateVariables": []},
        "contexts": {"contexts": []},
    }
    return empty_map.get(prompt_id, {})
