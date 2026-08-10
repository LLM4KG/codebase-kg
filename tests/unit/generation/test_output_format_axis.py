"""Tests for the run-level `output_format` axis.

The axis is only useful if one value reaches *both* ends: the instruction the
model reads and the applier the container runs. A run whose prompt asked for
SEARCH/REPLACE blocks while the harness ran `git apply` would fail 100% of
candidates for a reason that has nothing to do with the format being measured.
"""

from __future__ import annotations

import pytest

from src.generation import orchestrator as orch
from src.generation.orchestrator import Candidate
from src.retrieval.config import RunConfig
from src.retrieval.kg_retriever import build_generation_prompt


# --------------------------------------------------------------------------- #
# Config                                                                      #
# --------------------------------------------------------------------------- #
def test_default_is_the_incumbent_format():
    """Every run config written before this axis existed must keep working."""
    run = RunConfig(run_id="r", model_id="m", model_provider="p")
    assert run.output_format == "unified_diff"


def test_unknown_format_is_rejected_at_config_load():
    with pytest.raises(ValueError, match="output_format"):
        RunConfig(run_id="r", model_id="m", model_provider="p", output_format="sed")


def test_run_toml_flattening_picks_up_the_format(tmp_path):
    from src.retrieval.config import _flatten_run_toml

    flat = _flatten_run_toml(
        {
            "run": {
                "run_id": "r",
                "model": {"model_id": "m", "model_provider": "p"},
                "generation": {"temperature": 0.0, "output_format": "search_replace"},
            }
        }
    )
    assert RunConfig(**flat).output_format == "search_replace"


# --------------------------------------------------------------------------- #
# Prompt side                                                                 #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "template,expected",
    [
        ("generation/instruction_unified_diff.jinja2", "unified diff"),
        ("generation/instruction_search_replace.jinja2", "<<<<<<< SEARCH"),
        ("generation/instruction_whole_file.jinja2", "entire"),
    ],
)
def test_only_the_instruction_block_varies(template, expected):
    """The system prompt, spec and context must be byte-identical across formats,
    so a format comparison differs in exactly one block of text."""
    prompt = build_generation_prompt("fix the bug", "## CONTEXT", template)
    assert expected in prompt
    assert "senior React.js engineer" in prompt   # shared system prompt
    assert "fix the bug" in prompt
    assert "## CONTEXT" in prompt


# --------------------------------------------------------------------------- #
# End-to-end through the orchestrator                                         #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "fmt,marker",
    [
        ("unified_diff", "unified diff"),
        ("search_replace", "<<<<<<< SEARCH"),
        ("whole_file", "entire"),
    ],
)
async def test_override_reaches_the_prompt(wired, fmt, marker):
    cand = Candidate(
        run_id="r", run_name="claude_primary", task_id="P1",
        project_name="rsc", condition="floor", index=1,
    )
    await orch.run_one_candidate(
        cand, timeouts={}, llm_call_factory=wired["llm_factory"], output_format=fmt
    )
    assert marker in wired["gen"][0]["prompt"]


async def test_override_reaches_the_harness(wired):
    """The applier must be told the same format the prompt asked for."""
    cand = Candidate(
        run_id="r", run_name="claude_primary", task_id="P1",
        project_name="rsc", condition="floor", index=1,
    )
    await orch.run_one_candidate(
        cand,
        timeouts={},
        llm_call_factory=wired["llm_factory"],
        output_format="search_replace",
    )
    assert wired["harness"][0]["output_format"] == "search_replace"


async def test_metadata_records_the_format_and_the_parse_counts(wired):
    import json

    cand = Candidate(
        run_id="r", run_name="claude_primary", task_id="P1",
        project_name="rsc", condition="floor", index=1,
    )
    await orch.run_one_candidate(
        cand, timeouts={}, llm_call_factory=wired["llm_factory"], output_format="unified_diff"
    )
    meta = json.loads(
        (wired["artifacts_root"] / "r" / "P1__floor__n1" / "metadata.json").read_text()
    )
    assert meta["output_format"] == "unified_diff"
    assert {"edit_count", "malformed_blocks", "elided"} <= meta.keys()
