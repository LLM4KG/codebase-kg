"""Tests for read_stage_detail() and read_apply_mode().

The entrypoint redirects each stage's output into its own file inside the
container's output dir, so the docker subprocess's stdout/stderr are empty on a
candidate-side failure. These two readers are what put the failure reason and
the strict-vs-lenient apply decision back into the result record.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.harness.models import HarnessStage
from src.harness.runner import read_apply_mode, read_stage_detail


class TestReadStageDetail:
    def test_diff_apply_fail_reads_apply_stderr(self, tmp_path: Path):
        (tmp_path / "apply_stderr.log").write_text(
            "error: patch fragment without header at line 46"
        )
        detail = read_stage_detail(tmp_path, HarnessStage.diff_apply_fail)
        assert detail is not None
        assert "patch fragment without header" in detail

    def test_build_fail_reads_build_log(self, tmp_path: Path):
        (tmp_path / "build.log").write_text("TS2698: Spread types may only be created…")
        assert "TS2698" in read_stage_detail(tmp_path, HarnessStage.build_fail)

    def test_test_fail_prefers_stderr_over_stdout(self, tmp_path: Path):
        (tmp_path / "test_stdout.log").write_text("from stdout")
        (tmp_path / "test_stderr.log").write_text("from stderr")
        assert read_stage_detail(tmp_path, HarnessStage.test_fail) == "from stderr"

    def test_falls_through_to_next_candidate_when_first_is_empty(self, tmp_path: Path):
        # Jest writes its summary to stdout and leaves stderr empty; an empty
        # first-choice file must not mask the log that has the real content.
        (tmp_path / "test_stderr.log").write_text("   \n")
        (tmp_path / "test_stdout.log").write_text("Tests: 1 failed")
        assert read_stage_detail(tmp_path, HarnessStage.test_fail) == "Tests: 1 failed"

    def test_returns_none_when_no_log_exists(self, tmp_path: Path):
        assert read_stage_detail(tmp_path, HarnessStage.diff_apply_fail) is None

    def test_returns_none_for_stage_with_no_mapped_log(self, tmp_path: Path):
        assert read_stage_detail(tmp_path, HarnessStage.test_pass) is None
        assert read_stage_detail(tmp_path, HarnessStage.harness_error) is None

    def test_keeps_the_tail_when_truncating(self, tmp_path: Path):
        # Compilers and test runners put the real error last, so the tail is
        # the half worth keeping.
        (tmp_path / "build.log").write_text("A" * 500 + "REAL_ERROR_HERE")
        detail = read_stage_detail(tmp_path, HarnessStage.build_fail, max_chars=100)
        assert "REAL_ERROR_HERE" in detail
        assert detail.startswith("…[truncated]…")
        assert len(detail) < 200

    def test_decodes_invalid_utf8_without_raising(self, tmp_path: Path):
        (tmp_path / "build.log").write_bytes(b"before \xff\xfe after")
        detail = read_stage_detail(tmp_path, HarnessStage.build_fail)
        assert "before" in detail and "after" in detail


class TestReadApplyMode:
    def test_strict_when_no_marker_but_apply_happened(self, tmp_path: Path):
        (tmp_path / "apply.log").write_text("")
        assert read_apply_mode(tmp_path, HarnessStage.test_pass) == "strict"

    def test_recount_when_marker_present(self, tmp_path: Path):
        (tmp_path / "apply.log").write_text("")
        (tmp_path / "apply_mode.txt").write_text("recount\n")
        assert read_apply_mode(tmp_path, HarnessStage.test_pass) == "recount"

    @pytest.mark.parametrize(
        "stage",
        [HarnessStage.diff_apply_fail, HarnessStage.timeout_at_apply],
    )
    def test_none_when_diff_never_applied(self, tmp_path: Path, stage):
        (tmp_path / "apply.log").write_text("")
        assert read_apply_mode(tmp_path, stage) is None

    def test_none_when_container_never_reached_apply(self, tmp_path: Path):
        assert read_apply_mode(tmp_path, HarnessStage.harness_error) is None


class TestApplyModeTiers:
    """The three-tier ladder distinguishes verified placement from unverified.

    `-C0` disables context matching, so a hunk is placed by line number alone.
    Observed in the 2026-07-23 pilot: a candidate targeting `@@ -100` for code
    living at line 286 was applied anyway, splicing statements mid-expression
    and turning what should have been diff_apply_fail into build_fail.
    """

    def test_recount_c0_is_read_back(self, tmp_path):
        (tmp_path / "apply.log").write_text("")
        (tmp_path / "apply_mode.txt").write_text("recount_c0\n")
        assert read_apply_mode(tmp_path, HarnessStage.build_fail) == "recount_c0"

    def test_empty_marker_assumes_least_trusted_tier(self, tmp_path):
        """A truncated marker must not be read as the safest tier."""
        (tmp_path / "apply.log").write_text("")
        (tmp_path / "apply_mode.txt").write_text("")
        assert read_apply_mode(tmp_path, HarnessStage.test_pass) == "recount_c0"

    def test_placement_verified_classification(self):
        from src.harness.runner import is_placement_verified

        assert is_placement_verified("strict")
        assert is_placement_verified("recount")
        assert not is_placement_verified("recount_c0")
        assert not is_placement_verified(None)
