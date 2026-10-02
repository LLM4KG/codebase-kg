"""Condition + run config loading from the TOML hierarchy."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

# Narrow import of two constants only. `edit_formats.base` imports nothing from
# `retrieval`, so this does not create a cycle — but keep it that way.
from src.generation.edit_formats.base import DEFAULT_FORMAT, known_formats

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

logger = logging.getLogger(__name__)


class RetrievalConditionConfig(BaseModel):
    """Loaded from conditions/base/*.toml."""

    condition_id: str
    retriever: str
    format_variant: str = "A"
    max_rounds: int = 1
    retriever_params: dict[str, Any] = Field(default_factory=dict)


class RunConfig(BaseModel):
    """Loaded from conditions/runs/*.toml.

    Flattens the nested TOML structure ([run], [run.model], [run.generation])
    into a single flat model for easy consumption.
    """

    run_id: str
    model_id: str
    model_provider: str
    temperature: float = 0.0
    max_tokens: int = 4096
    reasoning: bool | None = None

    # How the generator is asked to express an edit: unified_diff |
    # search_replace | whole_file. Run-level, NOT condition-level, so the format
    # is uniform across all six conditions by construction — a per-condition
    # setting would silently permit arms that differ in two variables at once.
    # Default keeps every pre-existing run config loading unchanged.
    output_format: str = DEFAULT_FORMAT

    @model_validator(mode="after")
    def _validate_output_format(self) -> RunConfig:
        if self.output_format not in known_formats():
            raise ValueError(
                f"RunConfig {self.run_id!r} has output_format={self.output_format!r} — "
                f"expected one of {', '.join(known_formats())}"
            )
        return self

    @model_validator(mode="after")
    def _warn_nonzero_temperature(self) -> RunConfig:
        if self.temperature != 0.0:
            logger.warning(
                "RunConfig %r has temperature=%.2f — expected 0.0 "
                "(cross-model invariant D-LLM1)",
                self.run_id,
                self.temperature,
            )
        return self


class ExperimentConfig(BaseModel):
    """Combined config for a single experiment execution."""

    run: RunConfig
    condition: RetrievalConditionConfig


def _flatten_run_toml(data: dict[str, Any]) -> dict[str, Any]:
    """Flatten the nested run TOML structure into RunConfig fields."""
    run = data.get("run", {})
    model = run.get("model", {})
    generation = run.get("generation", {})
    provider_params = generation.get("provider_params", {})

    flat: dict[str, Any] = {
        "run_id": run.get("run_id"),
        "model_id": model.get("model_id"),
        "model_provider": model.get("model_provider"),
        "temperature": generation.get("temperature", 0.0),
        "max_tokens": generation.get("max_tokens", 4096),
        "output_format": generation.get("output_format", DEFAULT_FORMAT),
    }

    if "reasoning" in provider_params:
        flat["reasoning"] = provider_params["reasoning"]

    return flat


def load_condition_config(
    condition_name: str,
    conditions_dir: str | Path = "conditions",
) -> RetrievalConditionConfig:
    """Load conditions/base/{condition_name}.toml on its own.

    Split out of `load_experiment_config` for callers that need only what a
    condition *is* — which retriever it dispatches to — and have no run in hand
    (`_preflight_dense_key`). Dispatch keys on `retriever`, so anything deciding
    "is this the dense arm?" must read the field rather than match the name.
    """
    condition_path = Path(conditions_dir) / "base" / f"{condition_name}.toml"
    if not condition_path.exists():
        raise FileNotFoundError(f"Condition config not found: {condition_path}")

    with open(condition_path, "rb") as f:
        condition_data = tomllib.load(f)

    return RetrievalConditionConfig(**condition_data)


def load_experiment_config(
    run_name: str,
    condition_name: str,
    conditions_dir: str | Path = "conditions",
) -> ExperimentConfig:
    """Load a run + condition config pair.

    Reads:
      - conditions/runs/{run_name}.toml
      - conditions/base/{condition_name}.toml
    """
    base = Path(conditions_dir)

    run_path = base / "runs" / f"{run_name}.toml"
    if not run_path.exists():
        raise FileNotFoundError(f"Run config not found: {run_path}")

    condition_config = load_condition_config(condition_name, conditions_dir)

    with open(run_path, "rb") as f:
        run_data = tomllib.load(f)

    run_config = RunConfig(**_flatten_run_toml(run_data))

    return ExperimentConfig(run=run_config, condition=condition_config)
