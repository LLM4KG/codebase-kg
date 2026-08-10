"""Harness result models: the stage-classified outcome of running a candidate diff."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class HarnessStage(str, Enum):
    diff_apply_fail = "diff_apply_fail"
    install_fail = "install_fail"
    build_fail = "build_fail"
    setup_crash = "setup_crash"
    test_fail = "test_fail"
    test_pass = "test_pass"
    timeout_at_apply = "timeout_at_apply"
    timeout_at_install = "timeout_at_install"
    timeout_at_build = "timeout_at_build"
    timeout_at_test = "timeout_at_test"
    harness_error = "harness_error"  # infra-side failure (docker itself errored), not a candidate outcome


class HarnessResult(BaseModel):
    task_id: str
    candidate_id: str
    condition: str
    model: str
    stage: HarnessStage
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: float
    timeout_used_ms: int

    # Tail of the in-container log for the stage that actually failed
    # (apply_stderr.log, install.log, build.log, test_stderr.log). The entrypoint
    # redirects each stage's output into a file, so the docker subprocess's own
    # stdout/stderr above are empty on a candidate-side failure — without this,
    # the reason for a failure is discarded.
    stage_detail: str | None = None

    # Which tier applied the candidate's edit (docker/entrypoint.sh), or None if
    # it never applied. The vocabulary is per output format:
    #
    #   unified_diff    "strict"      — plain `git apply`
    #                   "recount"     — line counts recomputed, context verified
    #                   "recount_c0"  — context matching off; placement UNVERIFIED
    #   search_replace  "exact_unique"— every SEARCH matched exactly once
    #   whole_file      "whole_file"  — complete bodies written
    #                   "whole_file_elided" — a body was abbreviated; UNVERIFIED
    #
    # The split that matters is verified vs quarantined, not which format
    # produced it. `strict`, `recount`, `exact_unique` and `whole_file` all mean
    # the applied code is the code the model wrote. `recount_c0` and
    # `whole_file_elided` do not: the first places hunks by line number alone, so
    # a candidate can be spliced into the wrong location; the second writes a
    # body the model truncated with "... rest unchanged". Both then fail (or
    # pass) later stages for reasons unrelated to their content.
    # Report quarantined outcomes separately; never fold them into pass counts.
    # See PLACEMENT_VERIFIED_MODES / QUARANTINED_MODES in src/harness/runner.py.
    apply_mode: str | None = None

    # Why the apply step failed, when it did. `diff_apply_fail` on its own
    # conflates three different things — the pilot's 15 floor candidates were
    # all "diff_apply_fail" whether they miscounted hunk lines, invented a file
    # path, or invented the file's contents, and the distinction is exactly what
    # the floor-vs-KG reading turned on. One of:
    #   "line_arithmetic"  — hunk header counts disagree with the hunk body
    #   "context_mismatch" — the surrounding lines don't match the file
    #   "file_not_found"   — the target path does not exist in the repo
    #   "search_not_found" — the SEARCH text appears nowhere in the file
    #   "ambiguous_match"  — the SEARCH text appears more than once
    #   "malformed_blocks" — the model tried to emit edits; none could be parsed
    #   "empty_edit"       — the model produced nothing parseable at all
    #   None               — the apply step succeeded, or never ran
    apply_reason: str | None = None
