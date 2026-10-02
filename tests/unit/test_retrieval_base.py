"""Tests for the Phase 2 retrieval scaffolding."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.retrieval.base import Retriever
from src.retrieval.config import (
    ExperimentConfig,
    RetrievalConditionConfig,
    RunConfig,
    load_experiment_config,
)
from src.retrieval.models import RetrievalResult, RoundRecord
from src.retrieval.round_loop import STOP_TOKENS, execute_retrieval, is_stop_signal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_run_toml(path: Path, run_id: str = "test_run", model_id: str = "claude-sonnet-4-20250514") -> None:
    """Write a minimal run TOML matching the nested structure."""
    (path / "runs").mkdir(parents=True, exist_ok=True)
    (path / "runs" / f"{run_id}.toml").write_text(
        f"""\
[run]
run_id = "{run_id}"

[run.model]
model_id = "{model_id}"
model_provider = "anthropic"

[run.generation]
temperature = 0.0
max_tokens = 4096
"""
    )


def _write_condition_toml(
    path: Path,
    condition_id: str = "floor",
    retriever: str = "floor",
) -> None:
    """Write a minimal condition TOML."""
    (path / "base").mkdir(parents=True, exist_ok=True)
    (path / "base" / f"{condition_id}.toml").write_text(
        f"""\
condition_id = "{condition_id}"
retriever = "{retriever}"
format_variant = "A"
max_rounds = 1

[retriever_params]
"""
    )


class StubRetriever(Retriever):
    """Minimal concrete retriever for testing."""

    async def retrieve(
        self,
        spec: str,
        project_id: str,
        repo_root: str | Path,
        max_rounds: int = 1,
    ) -> RetrievalResult:
        return RetrievalResult(
            context=f"context for: {spec}",
            rounds=[
                RoundRecord(
                    round_number=1,
                    query=spec,
                    retrieved_files=["src/App.jsx"],
                    context_snippet="snippet",
                    token_count=42,
                )
            ],
            retriever_name=self.config.retriever,
            condition_id=self.config.condition_id,
            total_token_count=42,
        )


# ---------------------------------------------------------------------------
# Config loading tests
# ---------------------------------------------------------------------------


class TestConfigLoading:
    def test_load_experiment_config(self, tmp_path: Path):
        _write_run_toml(tmp_path, run_id="claude_primary")
        _write_condition_toml(tmp_path, condition_id="kg_augmented", retriever="kg_augmented")

        cfg = load_experiment_config("claude_primary", "kg_augmented", conditions_dir=tmp_path)

        assert cfg.run.run_id == "claude_primary"
        assert cfg.run.model_id == "claude-sonnet-4-20250514"
        assert cfg.run.model_provider == "anthropic"
        assert cfg.run.temperature == 0.0
        assert cfg.condition.condition_id == "kg_augmented"
        assert cfg.condition.retriever == "kg_augmented"
        assert cfg.condition.format_variant == "A"
        assert cfg.condition.max_rounds == 1

    def test_missing_run_raises(self, tmp_path: Path):
        _write_condition_toml(tmp_path)
        with pytest.raises(FileNotFoundError, match="Run config not found"):
            load_experiment_config("nonexistent", "floor", conditions_dir=tmp_path)

    def test_missing_condition_raises(self, tmp_path: Path):
        _write_run_toml(tmp_path)
        with pytest.raises(FileNotFoundError, match="Condition config not found"):
            load_experiment_config("test_run", "nonexistent", conditions_dir=tmp_path)

    def test_deepseek_reasoning_field(self, tmp_path: Path):
        (tmp_path / "runs").mkdir(parents=True, exist_ok=True)
        (tmp_path / "runs" / "deepseek.toml").write_text("""\
[run]
run_id = "deepseek_robustness"

[run.model]
model_id = "openrouter/deepseek/deepseek-chat-v3.1"
model_provider = "openrouter"

[run.generation]
temperature = 0.0
max_tokens = 8192

[run.generation.provider_params]
reasoning = false
""")
        _write_condition_toml(tmp_path)

        cfg = load_experiment_config("deepseek", "floor", conditions_dir=tmp_path)
        assert cfg.run.reasoning is False

    def test_loads_real_condition_tomls(self):
        """Verify the 6 committed condition TOML stubs parse correctly."""
        conditions_dir = Path("conditions")
        if not (conditions_dir / "base").exists():
            pytest.skip("conditions/base not present")

        for name in ["floor", "whole_file", "bm25", "text_emb_3_large", "nomic_embed_code", "kg_augmented"]:
            cfg = RetrievalConditionConfig(
                **_load_toml(conditions_dir / "base" / f"{name}.toml")
            )
            assert cfg.condition_id == name
            assert cfg.retriever == name

    def test_hardened_kg_condition_differs_only_in_anchor_resolution(self):
        """kg_augmented_hardened is kg_augmented plus one retriever_param (WP8).

        It is the one committed condition whose `retriever` is not its `condition_id`:
        both arms are the same retriever class, and that is the point — the published
        arm must stay byte-identical while the hardened one is measured beside it.
        """
        conditions_dir = Path("conditions") / "base"
        if not conditions_dir.exists():
            pytest.skip("conditions/base not present")

        base = RetrievalConditionConfig(**_load_toml(conditions_dir / "kg_augmented.toml"))
        hardened = RetrievalConditionConfig(**_load_toml(conditions_dir / "kg_augmented_hardened.toml"))

        assert base.retriever_params.get("anchor_resolution") is None  # defaults to strict
        assert hardened.condition_id == "kg_augmented_hardened"
        assert hardened.retriever == base.retriever == "kg_augmented"
        assert hardened.format_variant == base.format_variant
        assert hardened.max_rounds == base.max_rounds
        assert hardened.retriever_params == {"anchor_resolution": "hardened"}


def _load_toml(path: Path) -> dict:
    import sys
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        import tomli as tomllib
    with open(path, "rb") as f:
        return tomllib.load(f)


# ---------------------------------------------------------------------------
# Temperature validation
# ---------------------------------------------------------------------------


class TestTemperatureValidation:
    def test_zero_temperature_no_warning(self, caplog):
        RunConfig(run_id="test", model_id="m", model_provider="p", temperature=0.0)
        assert "temperature" not in caplog.text

    def test_nonzero_temperature_warns(self, caplog):
        import logging
        with caplog.at_level(logging.WARNING):
            RunConfig(run_id="test", model_id="m", model_provider="p", temperature=0.7)
        assert "temperature" in caplog.text
        assert "0.70" in caplog.text


# ---------------------------------------------------------------------------
# Retriever base class
# ---------------------------------------------------------------------------


class TestRetrieverBase:
    def test_concrete_subclass_works(self):
        config = RetrievalConditionConfig(condition_id="floor", retriever="floor")
        retriever = StubRetriever(config)
        assert retriever.config.condition_id == "floor"

    def test_next_query_raises_not_implemented(self):
        config = RetrievalConditionConfig(condition_id="floor", retriever="floor")
        retriever = StubRetriever(config)
        with pytest.raises(NotImplementedError, match="does not support iterative"):
            retriever.next_query([])


# ---------------------------------------------------------------------------
# Round loop and execute_retrieval
# ---------------------------------------------------------------------------


class TestExecuteRetrieval:
    async def test_single_round_returns_one_record(self):
        config = RetrievalConditionConfig(condition_id="floor", retriever="floor")
        retriever = StubRetriever(config)

        result = await execute_retrieval(
            retriever=retriever,
            spec="Add a button",
            project_id="test_project",
            repo_root="/tmp/repo",
            max_rounds=1,
        )

        assert isinstance(result, RetrievalResult)
        assert len(result.rounds) == 1
        assert result.rounds[0].round_number == 1
        assert result.rounds[0].query == "Add a button"
        assert result.retriever_name == "floor"
        assert result.condition_id == "floor"

    async def test_multi_round_stops_on_not_implemented(self):
        config = RetrievalConditionConfig(condition_id="floor", retriever="floor")
        retriever = StubRetriever(config)

        result = await execute_retrieval(
            retriever=retriever,
            spec="Add a button",
            project_id="test_project",
            repo_root="/tmp/repo",
            max_rounds=3,
        )

        assert len(result.rounds) == 1


# ---------------------------------------------------------------------------
# STOP detection
# ---------------------------------------------------------------------------


class TestStopDetection:
    @pytest.mark.parametrize("value", [None, "STOP", "[STOP]", "<STOP>", " STOP ", " [stop] "])
    def test_stop_signals(self, value):
        assert is_stop_signal(value) is True

    @pytest.mark.parametrize("value", ["continue querying", "get more context", ""])
    def test_non_stop_signals(self, value):
        assert is_stop_signal(value) is False


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class TestRetrievalResult:
    def test_required_fields(self):
        result = RetrievalResult(
            context="ctx",
            rounds=[],
            retriever_name="floor",
            condition_id="floor",
            total_token_count=0,
        )
        assert result.context == "ctx"
        assert result.metadata == {}

    def test_metadata_default(self):
        result = RetrievalResult(
            context="ctx",
            rounds=[],
            retriever_name="bm25",
            condition_id="bm25",
            total_token_count=100,
            metadata={"classifier_output": "ui_component"},
        )
        assert result.metadata["classifier_output"] == "ui_component"


class TestExperimentConfig:
    def test_combines_run_and_condition(self, tmp_path: Path):
        _write_run_toml(tmp_path, run_id="qwen_robustness", model_id="openrouter/qwen/qwen-2.5-coder-32b-instruct")
        _write_condition_toml(tmp_path, condition_id="bm25", retriever="bm25")

        cfg = load_experiment_config("qwen_robustness", "bm25", conditions_dir=tmp_path)

        assert isinstance(cfg, ExperimentConfig)
        assert cfg.run.model_id == "openrouter/qwen/qwen-2.5-coder-32b-instruct"
        assert cfg.condition.retriever == "bm25"
