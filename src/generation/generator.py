"""The generator step: build the prompt, make the logged LLM call, parse the edit.

WI3 stopped at a rendered context block. This module adds the generator call —
`logged_llm_call(..., call_purpose="generator")` — reusing
`build_generation_prompt` for prompt assembly. The `llm_call` argument is an
injectable seam so the orchestrator can run a mock generator (offline,
zero-token) without touching this logic.

The output format is a run-level axis (`run.output_format`). This module reads
the format's instruction template and extractor out of the registry and is
otherwise format-blind — which is what keeps the three arms differing in exactly
one thing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from src.generation.edit_formats import EditScript, get_edit_format
from src.llm.logger import LLMResponse, logged_llm_call
from src.retrieval.config import RunConfig
from src.retrieval.kg_retriever import build_generation_prompt


@dataclass
class GenerationResult:
    prompt: str
    response_text: str
    # The candidate payload handed to the harness. For `unified_diff` this is the
    # raw patch text (unchanged from WI4); for the other formats it is the JSON
    # edit script that `docker/apply_edits.js` consumes. Named `diff` throughout
    # because the harness argument, the artifact filename and every downstream
    # consumer already are.
    diff: str
    script: EditScript
    usage: dict | None
    latency_ms: float


async def generate_candidate_diff(
    *,
    spec: str,
    context_block: str,
    run: RunConfig,
    condition_id: str,
    run_id: str,
    log_dir: Path | None = None,
    llm_call: Callable[..., Any] = logged_llm_call,
) -> GenerationResult:
    """Generate one candidate diff for a task spec + retrieved context block.

    Both the retriever's internal classifier and this generator use `run.model_id`
    — the same model within a run (D-LLM3). `temperature`/`max_tokens` come from
    the run config (temperature is 0.0 per D-LLM1).
    """
    edit_format = get_edit_format(run.output_format)
    prompt = build_generation_prompt(
        spec, context_block, instruction_template=edit_format.instruction_template
    )
    messages = [{"role": "user", "content": prompt}]

    resp: LLMResponse = await llm_call(
        messages,
        model=run.model_id,
        run_id=run_id,
        condition_id=condition_id,
        call_purpose="generator",
        temperature=run.temperature,
        max_tokens=run.max_tokens,
        log_dir=log_dir,
    )

    script = edit_format.extract(resp.text)
    payload = script.raw_patch if run.output_format == "unified_diff" else script.to_json()
    return GenerationResult(
        prompt=prompt,
        response_text=resp.text,
        diff=payload,
        script=script,
        usage=resp.usage,
        latency_ms=resp.latency_ms,
    )
