"""WP5 graded outcome scale (IJCKG revision plan, WP5 acceptance).

Every candidate maps to exactly one outcome:

    never_applied   the edit did not apply            diff_apply_fail, timeout_at_apply
    build_fail      applied, but did not build        install_fail, build_fail, setup_crash,
                                                      timeout_at_install, timeout_at_build
    test_fail       built, but failed the test        test_fail, timeout_at_test
    passed          test_pass with a placement-verified apply_mode

and two exclusions, reported in their own columns and never folded into the scale:

    harness_error   infrastructure failure, not a candidate outcome
    quarantined     apply_mode in QUARANTINED_MODES (placement unverified), whatever the stage

The trust vocabulary is imported from the harness, never re-listed, so this report
cannot disagree with the runner about what counts as a pass.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from src.harness.models import HarnessStage
from src.harness.runner import PLACEMENT_VERIFIED_MODES, QUARANTINED_MODES

SCALE = ("passed", "test_fail", "build_fail", "never_applied")
EXCLUDED = ("quarantined", "harness_error")
OUTCOMES = SCALE + EXCLUDED

STAGE_TO_OUTCOME: dict[HarnessStage, str] = {
    HarnessStage.diff_apply_fail: "never_applied",
    HarnessStage.timeout_at_apply: "never_applied",
    HarnessStage.install_fail: "build_fail",
    HarnessStage.build_fail: "build_fail",
    HarnessStage.setup_crash: "build_fail",
    HarnessStage.timeout_at_install: "build_fail",
    HarnessStage.timeout_at_build: "build_fail",
    HarnessStage.test_fail: "test_fail",
    HarnessStage.timeout_at_test: "test_fail",
    HarnessStage.test_pass: "passed",
    HarnessStage.harness_error: "harness_error",
}


class UnexpectedResult(ValueError):
    pass


def grade(row: dict) -> str:
    """The outcome of one harness result row (a `results.jsonl` line)."""
    stage = HarnessStage(row["stage"])
    mode = row.get("apply_mode")
    if stage is HarnessStage.harness_error:
        return "harness_error"
    if mode in QUARANTINED_MODES:
        return "quarantined"
    outcome = STAGE_TO_OUTCOME[stage]
    applied = outcome in ("passed", "test_fail", "build_fail")
    if applied and mode not in PLACEMENT_VERIFIED_MODES:
        # A candidate past the apply step must have a recorded tier. Anything else
        # is a harness bookkeeping fault, and must not be counted silently.
        raise UnexpectedResult(f"{row['candidate_id']}: stage {stage.value} with apply_mode {mode!r}")
    if outcome == "never_applied" and mode is not None:
        raise UnexpectedResult(f"{row['candidate_id']}: never applied but apply_mode {mode!r}")
    return outcome


def patch_hash(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
