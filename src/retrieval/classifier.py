"""LLM-based task classifier + anchor extractor for the KG-augmented retriever.

One logged LLM call receives the raw task spec and returns the task type plus the
anchor component/hook names (and optional route paths) used to scope the Cypher
templates. Per D-LLM3 the caller passes the run's model — no cross-model mixing.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Literal

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, Field, ValidationError

from src.llm.logger import logged_llm_call

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"
_CLASSIFIER_TEMPLATE = "classifier.jinja2"

TaskType = Literal["bug_fix", "feature_addition", "refactoring"]

_env: Environment | None = None


def _get_env() -> Environment:
    global _env
    if _env is None:
        _env = Environment(
            loader=FileSystemLoader(str(PROMPTS_DIR)),
            autoescape=select_autoescape([]),
            keep_trailing_newline=True,
        )
    return _env


class ClassifierResult(BaseModel):
    task_type: TaskType
    anchor_names: list[str] = Field(default_factory=list)
    anchor_routes: list[str] = Field(default_factory=list)


def _extract_json_object(text: str) -> dict | None:
    """Best-effort extraction of the first JSON object from an LLM response."""
    text = text.strip()
    # Strip markdown fences if the model added them despite instructions.
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Fallback: grab the outermost {...} span.
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None


def parse_classifier_response(text: str) -> ClassifierResult:
    """Parse an LLM response into a ClassifierResult.

    Degrades gracefully (documented L5 fallback): on malformed JSON or an invalid
    task_type, returns a bug_fix result with empty anchors rather than raising —
    the templates then fall back to project-wide summaries.
    """
    data = _extract_json_object(text)
    if data is None:
        logger.warning("Classifier response was not valid JSON; using empty-anchor fallback")
        return ClassifierResult(task_type="bug_fix", anchor_names=[], anchor_routes=[])
    try:
        return ClassifierResult(**data)
    except ValidationError as exc:
        logger.warning("Classifier response failed validation (%s); using empty-anchor fallback", exc)
        task_type = data.get("task_type")
        if task_type not in ("bug_fix", "feature_addition", "refactoring"):
            task_type = "bug_fix"
        names = data.get("anchor_names") or []
        routes = data.get("anchor_routes") or []
        return ClassifierResult(
            task_type=task_type,
            anchor_names=[str(n) for n in names if isinstance(n, (str, int))],
            anchor_routes=[str(r) for r in routes if isinstance(r, (str, int))],
        )


async def classify_task(
    spec: str,
    *,
    model: str,
    run_id: str,
    condition_id: str,
    log_dir: Path | None = None,
    temperature: float = 0.0,
) -> ClassifierResult:
    """Classify a task spec and extract anchors via one logged LLM call."""
    prompt = _get_env().get_template(_CLASSIFIER_TEMPLATE).render(spec=spec)

    response = await logged_llm_call(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        run_id=run_id,
        condition_id=condition_id,
        call_purpose="classifier",
        temperature=temperature,
        max_tokens=512,
        log_dir=log_dir,
    )
    return parse_classifier_response(response.text)
