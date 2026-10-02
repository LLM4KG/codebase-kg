"""WP5 graded outcome scale."""

import pytest

from src.evaluation.outcomes import OUTCOMES, STAGE_TO_OUTCOME, UnexpectedResult, grade
from src.harness.models import HarnessStage
from src.harness.runner import PLACEMENT_VERIFIED_MODES, QUARANTINED_MODES


def row(stage, mode=None):
    return {"candidate_id": "P1__bm25__n1", "stage": stage, "apply_mode": mode}


def test_every_harness_stage_has_exactly_one_outcome():
    assert set(STAGE_TO_OUTCOME) == set(HarnessStage)
    assert set(STAGE_TO_OUTCOME.values()) <= set(OUTCOMES)


@pytest.mark.parametrize("stage, mode, outcome", [
    ("test_pass", "exact_unique", "passed"),
    ("test_pass", "strict", "passed"),
    ("test_fail", "exact_unique", "test_fail"),
    ("timeout_at_test", "exact_unique", "test_fail"),
    ("build_fail", "exact_unique", "build_fail"),
    ("install_fail", "recount", "build_fail"),
    ("setup_crash", "whole_file", "build_fail"),
    ("timeout_at_build", "exact_unique", "build_fail"),
    ("diff_apply_fail", None, "never_applied"),
    ("timeout_at_apply", None, "never_applied"),
    ("harness_error", None, "harness_error"),
    ("harness_error", "exact_unique", "harness_error"),
])
def test_grades(stage, mode, outcome):
    assert grade(row(stage, mode)) == outcome


@pytest.mark.parametrize("mode", sorted(QUARANTINED_MODES))
@pytest.mark.parametrize("stage", ["test_pass", "test_fail", "build_fail"])
def test_quarantined_is_never_a_pass_whatever_the_stage(stage, mode):
    assert grade(row(stage, mode)) == "quarantined"


def test_trust_vocabulary_is_the_harness_one():
    # A pass needs a verified tier; the verified and quarantined sets don't overlap.
    assert not PLACEMENT_VERIFIED_MODES & QUARANTINED_MODES


@pytest.mark.parametrize("stage, mode", [
    ("test_pass", None),          # passed without an apply tier: bookkeeping fault
    ("build_fail", None),
    ("diff_apply_fail", "exact_unique"),
])
def test_inconsistent_rows_raise_instead_of_being_counted(stage, mode):
    with pytest.raises(UnexpectedResult):
        grade(row(stage, mode))
