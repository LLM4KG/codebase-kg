"""Tests for the apply-tier trust vocabulary and the attributable failure reason.

Two separate jobs, both added with the output-format work:

`is_placement_verified` decides whether a candidate's downstream stage describes
the code the model actually wrote. Getting it wrong in the permissive direction
is how the 2026-07-23 leg's P2 `build_fail`s came to look like content results
when they were placement artefacts.

`read_apply_reason` splits `diff_apply_fail`, which previously covered
"miscounted hunk lines", "invented a path" and "invented the file's contents"
under one label — all 15 of that leg's floor candidates, for three different
reasons.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.harness.models import HarnessStage
from src.harness.runner import (
    PLACEMENT_VERIFIED_MODES,
    QUARANTINED_MODES,
    is_placement_verified,
    read_apply_mode,
    read_apply_reason,
)


class TestTrustVocabulary:
    @pytest.mark.parametrize(
        "mode", ["strict", "recount", "exact_unique", "whole_file"]
    )
    def test_verified_tiers(self, mode):
        assert is_placement_verified(mode)

    @pytest.mark.parametrize("mode", ["recount_c0", "whole_file_elided"])
    def test_quarantined_tiers_are_not_verified(self, mode):
        assert not is_placement_verified(mode)
        assert mode in QUARANTINED_MODES

    def test_never_applied_is_not_verified(self):
        assert not is_placement_verified(None)

    def test_never_applied_is_not_quarantined_either(self):
        """None must stay distinguishable from applied-but-untrustworthy: one is
        a candidate that produced nothing, the other a result to report apart."""
        assert None not in QUARANTINED_MODES

    def test_the_two_sets_are_disjoint(self):
        assert not (PLACEMENT_VERIFIED_MODES & QUARANTINED_MODES)

    def test_an_unknown_tier_is_treated_as_untrustworthy(self):
        """A tier added to the entrypoint without being classified here must not
        default into the pass counts."""
        assert not is_placement_verified("some_future_lenient_tier")


class TestReadApplyMode:
    def test_search_replace_exact_unique(self, tmp_path: Path):
        (tmp_path / "apply.log").write_text("")
        (tmp_path / "apply_mode.txt").write_text("exact_unique\n")
        assert read_apply_mode(tmp_path, HarnessStage.test_pass) == "exact_unique"

    def test_whole_file_elided(self, tmp_path: Path):
        (tmp_path / "apply.log").write_text("")
        (tmp_path / "apply_mode.txt").write_text("whole_file_elided\n")
        mode = read_apply_mode(tmp_path, HarnessStage.build_fail)
        assert mode == "whole_file_elided"
        assert not is_placement_verified(mode)

    def test_empty_marker_assumes_the_least_trustworthy_tier(self, tmp_path: Path):
        (tmp_path / "apply.log").write_text("")
        (tmp_path / "apply_mode.txt").write_text("\n")
        assert read_apply_mode(tmp_path, HarnessStage.test_pass) == "recount_c0"

    def test_no_marker_with_an_apply_log_means_strict_git(self, tmp_path: Path):
        (tmp_path / "apply.log").write_text("")
        assert read_apply_mode(tmp_path, HarnessStage.test_pass) == "strict"

    def test_apply_failure_has_no_mode(self, tmp_path: Path):
        (tmp_path / "apply_mode.txt").write_text("exact_unique\n")
        assert read_apply_mode(tmp_path, HarnessStage.diff_apply_fail) is None


class TestReadApplyReason:
    @pytest.mark.parametrize(
        "reason",
        [
            "line_arithmetic",
            "context_mismatch",
            "file_not_found",
            "search_not_found",
            "ambiguous_match",
            "malformed_blocks",
            "empty_edit",
        ],
    )
    def test_reasons_round_trip(self, tmp_path: Path, reason):
        (tmp_path / "apply_reason.txt").write_text(f"{reason}\n")
        assert read_apply_reason(tmp_path) == reason

    def test_absent_marker_means_the_apply_step_succeeded(self, tmp_path: Path):
        assert read_apply_reason(tmp_path) is None

    def test_empty_marker_is_none_not_empty_string(self, tmp_path: Path):
        (tmp_path / "apply_reason.txt").write_text("  \n")
        assert read_apply_reason(tmp_path) is None


class TestScratchDirIsolation:
    """`run_candidate` must not inherit the previous run's output files.

    Every reader in this module infers from *which files exist*. A strict
    `git apply` writes no `apply_mode.txt`, so a candidate id re-run after a
    lenient run reported the stale lenient tier — three byte-identical reference
    patches came back as `strict`, `recount` and `recount_c0` in one dry run.
    """

    async def test_stale_markers_are_cleared(self, tmp_path, monkeypatch):
        from types import SimpleNamespace

        import src.harness.runner as runner_mod
        from src.harness.tasks import PilotTask

        work = tmp_path / "work"
        stale = work / "cid" / "output"
        stale.mkdir(parents=True)
        (stale / "apply_mode.txt").write_text("recount_c0\n")
        (stale / "apply_reason.txt").write_text("context_mismatch\n")

        settings = SimpleNamespace(
            work_dir=str(work),
            memory_limit="1g",
            cpu_limit=1.0,
            network_mode="none",
            default_timeout_ms=1000,
            projects={
                "proj": SimpleNamespace(
                    image_tag="img", test_command="t", run_build=False,
                    build_command="b", test_env={}, extra_docker_env={},
                )
            },
        )

        async def fake_subprocess(argv, *, timeout_s, kill_cmd=None):
            out = work / "cid" / "output"
            (out / "stage.txt").write_text("test_pass\n")
            (out / "apply.log").write_text("")      # strict apply: no mode marker
            return 0, "", "", False

        monkeypatch.setattr(runner_mod, "run_subprocess_with_timeout", fake_subprocess)
        monkeypatch.setattr(runner_mod, "_write_harness_result", lambda *a, **k: None)

        task = PilotTask(
            task_id="T", project_id="proj", project_repo="r", git_commit="c",
            task_type="bug_fix", test_files=["a.test.ts"],
        )
        result = await runner_mod.run_candidate(
            candidate_diff="", task=task, condition="floor", model="m",
            candidate_id="cid", run_id="r", settings=settings,
        )
        assert result.apply_mode == "strict"
        assert result.apply_reason is None
