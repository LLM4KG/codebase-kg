"""Tests for HarnessStage / HarnessResult models."""

from __future__ import annotations

import json

from src.harness.models import HarnessResult, HarnessStage


def test_all_stage_values_are_plain_strings():
    expected = {
        "diff_apply_fail",
        "install_fail",
        "build_fail",
        "setup_crash",
        "test_fail",
        "test_pass",
        "timeout_at_apply",
        "timeout_at_install",
        "timeout_at_build",
        "timeout_at_test",
        "harness_error",
    }
    actual = {s.value for s in HarnessStage}
    assert actual == expected
    for stage in HarnessStage:
        assert isinstance(stage.value, str)
        assert stage.value == stage  # str-enum identity


def test_harness_result_roundtrips_json_with_spec_field_names():
    result = HarnessResult(
        task_id="P1",
        candidate_id="P1_kg_augmented_claude_0",
        condition="kg_augmented",
        model="anthropic/claude-sonnet-4-5",
        stage=HarnessStage.test_pass,
        exit_code=0,
        stdout="ok",
        stderr="",
        duration_ms=1234.5,
        timeout_used_ms=60000,
    )
    payload = json.loads(result.model_dump_json())
    assert set(payload.keys()) == {
        "task_id",
        "candidate_id",
        "condition",
        "model",
        "stage",
        "exit_code",
        "stdout",
        "stderr",
        "duration_ms",
        "timeout_used_ms",
        "stage_detail",
        "apply_mode",
        "apply_reason",
    }
    assert payload["stage"] == "test_pass"
    # Both default to null so results written before these fields existed still load.
    assert payload["stage_detail"] is None
    assert payload["apply_mode"] is None

    restored = HarnessResult.model_validate(payload)
    assert restored == result


def test_exit_code_accepts_none():
    result = HarnessResult(
        task_id="P1",
        candidate_id="c",
        condition="baseline",
        model="m",
        stage=HarnessStage.timeout_at_test,
        exit_code=None,
        stdout="",
        stderr="",
        duration_ms=0.0,
        timeout_used_ms=1000,
    )
    assert result.exit_code is None
