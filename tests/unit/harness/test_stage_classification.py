"""Table-driven tests for classify_stage()."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.harness.models import HarnessStage
from src.harness.runner import classify_stage


def _write_stage(output_dir: Path, content: str) -> None:
    (output_dir / "stage.txt").write_text(content)


@pytest.mark.parametrize(
    "stage_content,expected",
    [
        ("diff_apply_fail", HarnessStage.diff_apply_fail),
        ("install_fail", HarnessStage.install_fail),
        ("build_fail", HarnessStage.build_fail),
        ("setup_crash", HarnessStage.setup_crash),
        ("test_fail", HarnessStage.test_fail),
        ("test_pass", HarnessStage.test_pass),
        ("test_pass\n", HarnessStage.test_pass),  # trailing newline tolerated
    ],
)
def test_non_timeout_reads_stage_txt(tmp_path: Path, stage_content, expected):
    _write_stage(tmp_path, stage_content)
    assert classify_stage(tmp_path, timed_out=False, run_build=False) == expected


def test_missing_stage_txt_is_harness_error(tmp_path: Path):
    assert classify_stage(tmp_path, timed_out=False, run_build=False) == HarnessStage.harness_error


def test_unknown_stage_txt_is_harness_error(tmp_path: Path):
    _write_stage(tmp_path, "something_weird")
    assert classify_stage(tmp_path, timed_out=False, run_build=False) == HarnessStage.harness_error


@pytest.mark.parametrize(
    "files,run_build,expected",
    [
        # Nothing written yet -> hung during apply.
        ([], False, HarnessStage.timeout_at_apply),
        # apply done, nothing after, no build expected -> heading to test.
        (["apply.log"], False, HarnessStage.timeout_at_test),
        # apply done, nothing after, build expected -> heading to build.
        (["apply.log"], True, HarnessStage.timeout_at_build),
        # install log present -> hung during install.
        (["apply.log", "install.log"], False, HarnessStage.timeout_at_install),
        # build log present -> hung during build.
        (["apply.log", "build.log"], True, HarnessStage.timeout_at_build),
        # test log present -> hung during test (test dominates).
        (["apply.log", "test_stdout.log"], False, HarnessStage.timeout_at_test),
        (["apply.log", "build.log", "test_stderr.log"], True, HarnessStage.timeout_at_test),
    ],
)
def test_timeout_inference(tmp_path: Path, files, run_build, expected):
    for name in files:
        (tmp_path / name).write_text("x")
    assert classify_stage(tmp_path, timed_out=True, run_build=run_build) == expected
