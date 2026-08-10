"""Public entrypoint: apply a candidate diff in Docker, run tests, classify the outcome.

Work items 4/5 import `run_candidate` directly. The bash entrypoint owns "what does
failure vs. crash look like" (via output/stage.txt); this module stays thin and
unit-testable by monkeypatching the subprocess layer.
"""

from __future__ import annotations

import re
import shutil
import time
from pathlib import Path

from src.config import HarnessSettings, get_settings
from src.harness.models import HarnessResult, HarnessStage
from src.harness.process import run_subprocess_with_timeout
from src.harness.results import _write_harness_result
from src.harness.tasks import PilotTask

DEFAULT_TESTS_DIR = Path("tasks/pilot/tests")

# Docker container names must match [a-zA-Z0-9][a-zA-Z0-9_.-]*.
_NAME_SANITIZE_RE = re.compile(r"[^a-zA-Z0-9_.-]")


def _sanitize_container_name(candidate_id: str) -> str:
    name = _NAME_SANITIZE_RE.sub("_", candidate_id)
    if not name or not re.match(r"[a-zA-Z0-9]", name[0]):
        name = f"c_{name}"
    return name


def _derive_test_pattern(test_files: list[str]) -> str:
    """Jest --testPathPattern regex from test filenames (strip the .test.<ext> suffix)."""
    stems = [Path(f).name.split(".test.")[0] for f in test_files]
    return "|".join(stems)


def classify_stage(
    output_dir: Path, timed_out: bool, run_build: bool
) -> HarnessStage:
    """Determine the harness stage from the container's output directory.

    Non-timeout path: the bash entrypoint's `stage.txt` is the single source of
    truth. Timeout path: infer `timeout_at_*` from which stage log files exist.
    """
    if not timed_out:
        stage_file = output_dir / "stage.txt"
        if not stage_file.exists():
            return HarnessStage.harness_error
        content = stage_file.read_text(encoding="utf-8").strip()
        try:
            return HarnessStage(content)
        except ValueError:
            return HarnessStage.harness_error

    # Timeout inference: highest-progressed stage whose log file exists.
    if (output_dir / "test_stdout.log").exists() or (output_dir / "test_stderr.log").exists():
        return HarnessStage.timeout_at_test
    if (output_dir / "build.log").exists():
        return HarnessStage.timeout_at_build
    if (output_dir / "install.log").exists():
        return HarnessStage.timeout_at_install
    if not (output_dir / "apply.log").exists():
        return HarnessStage.timeout_at_apply
    # apply.log exists but nothing after it: hung heading into the next real stage.
    return HarnessStage.timeout_at_build if run_build else HarnessStage.timeout_at_test


# Which in-container log explains each failing stage. The entrypoint redirects
# every stage's output into its own file, so these are the only place a
# candidate-side failure reason exists.
_STAGE_LOG: dict[HarnessStage, tuple[str, ...]] = {
    HarnessStage.diff_apply_fail: ("apply_stderr.log", "apply.log"),
    HarnessStage.install_fail: ("install.log",),
    HarnessStage.build_fail: ("build.log",),
    HarnessStage.setup_crash: ("test_stderr.log", "test_stdout.log"),
    HarnessStage.test_fail: ("test_stderr.log", "test_stdout.log"),
    HarnessStage.timeout_at_apply: ("apply_stderr.log",),
    HarnessStage.timeout_at_install: ("install.log",),
    HarnessStage.timeout_at_build: ("build.log",),
    HarnessStage.timeout_at_test: ("test_stderr.log", "test_stdout.log"),
}

_STAGE_DETAIL_MAX_CHARS = 4000


def read_stage_detail(
    output_dir: Path, stage: HarnessStage, max_chars: int = _STAGE_DETAIL_MAX_CHARS
) -> str | None:
    """Return the tail of the log explaining `stage`, or None if there is none.

    Tail rather than head: compilers and test runners put the actual error last.
    """
    for name in _STAGE_LOG.get(stage, ()):
        path = output_dir / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        if not text:
            continue
        if len(text) > max_chars:
            text = "…[truncated]…\n" + text[-max_chars:]
        return text
    return None


def read_apply_mode(output_dir: Path, stage: HarnessStage) -> str | None:
    """Which tier applied the candidate's edit, or None if it never applied.

    The vocabulary is per output format — see `HarnessResult.apply_mode` — but
    the only distinction that matters downstream is verified vs quarantined.
    Verified means the applied code is the code the model wrote; quarantined
    means it may not be, so every later stage for such a candidate is describing
    something other than the model's output. **Quarantined results must be
    reported separately and never folded into pass counts.** See
    `is_placement_verified`.
    """
    if stage is HarnessStage.diff_apply_fail or stage.name.startswith("timeout_at_apply"):
        return None
    if not (output_dir / "apply.log").exists():
        return None
    marker = output_dir / "apply_mode.txt"
    if marker.exists():
        # An empty marker means the entrypoint reached the write but not its
        # value — assume the least trustworthy tier rather than the most.
        return marker.read_text(encoding="utf-8").strip() or "recount_c0"
    return "strict"


def read_apply_reason(output_dir: Path) -> str | None:
    """Why the apply step failed, or None when it succeeded / never ran.

    Written by `docker/apply_edits.js` for the edit-script formats. For
    `unified_diff`, `docker/entrypoint.sh` derives it from git's own stderr,
    since git reports the same three causes in prose.
    """
    marker = output_dir / "apply_reason.txt"
    if not marker.exists():
        return None
    return marker.read_text(encoding="utf-8").strip() or None


# Tiers where the applied code is confirmed to be the code the model wrote:
# git verified the hunk context, every SEARCH matched exactly once, or a
# complete file body was written.
PLACEMENT_VERIFIED_MODES = frozenset(
    {"strict", "recount", "exact_unique", "whole_file"}
)

# Tiers that applied *something* without confirming it is what the model meant.
# `recount_c0` places hunks by line number with context matching disabled;
# `whole_file_elided` writes a body the model abbreviated with a placeholder.
# Held as its own set rather than "not verified" so that None — never applied —
# stays distinguishable from applied-but-untrustworthy.
QUARANTINED_MODES = frozenset({"recount_c0", "whole_file_elided"})


def is_placement_verified(apply_mode: str | None) -> bool:
    """True when the applied code is confirmed to be the code the model wrote.

    False for the quarantined tiers and for None (never applied). Use this to
    separate trustworthy outcomes from ones that must be reported apart.
    """
    return apply_mode in PLACEMENT_VERIFIED_MODES


def _read_exit_code(output_dir: Path, docker_returncode: int | None) -> int | None:
    exit_file = output_dir / "exit_code.txt"
    if exit_file.exists():
        try:
            return int(exit_file.read_text(encoding="utf-8").strip())
        except ValueError:
            pass
    return docker_returncode


def _build_docker_run_argv(
    *,
    image_tag: str,
    container_name: str,
    settings: HarnessSettings,
    scratch_dir: Path,
    output_dir: Path,
    test_mounts: list[tuple[Path, str]],
    env: dict[str, str],
) -> list[str]:
    argv = [
        "docker", "run", "--rm",
        "--name", container_name,
        f"--memory={settings.memory_limit}",
        f"--cpus={settings.cpu_limit}",
        f"--network={settings.network_mode}",
        "-v", f"{scratch_dir / 'candidate.diff'}:/harness/candidate.diff:ro",
        "-v", f"{output_dir}:/harness/output",
    ]
    for src, dest in test_mounts:
        argv += ["-v", f"{src}:/app/{dest}:ro"]
    for key, value in env.items():
        argv += ["-e", f"{key}={value}"]
    argv.append(image_tag)
    return argv


async def run_candidate(
    *,
    candidate_diff: str,
    task: PilotTask,
    condition: str,
    model: str,
    candidate_id: str,
    run_id: str,
    timeout_ms: int | None = None,
    settings: HarnessSettings | None = None,
    results_dir: Path | None = None,
    tests_dir: Path = DEFAULT_TESTS_DIR,
    output_format: str = "unified_diff",
) -> HarnessResult:
    """Run one candidate edit through the Docker harness and return a classified result.

    `candidate_diff` carries the raw patch for `unified_diff` and the JSON edit
    script for the other formats; `output_format` tells the entrypoint which
    applier to use. The result JSON + JSONL index are flushed to disk before this
    returns.
    """
    harness_settings = settings or get_settings().harness
    project = harness_settings.projects[task.project_id]
    timeout_used_ms = timeout_ms if timeout_ms is not None else harness_settings.default_timeout_ms

    # Per-candidate scratch dir: candidate.diff + an output/ mount target.
    # Resolve to an absolute path — `docker run -v` treats a relative source as
    # a named volume, not a bind mount.
    scratch_dir = (Path(harness_settings.work_dir) / candidate_id).resolve()
    output_dir = scratch_dir / "output"

    # Wipe it first. Every reader here — `read_apply_mode`, `read_apply_reason`,
    # `read_stage_detail`, `classify_stage` — infers from *which files exist*, so
    # any file the current run does not happen to overwrite is silently read as
    # this run's result. A strict `git apply` writes no `apply_mode.txt`, so
    # re-running a candidate id that previously landed on a lenient tier
    # reported the old tier: three identical reference patches came back as
    # `strict`, `recount` and `recount_c0` in one dry run. Harmless while each
    # candidate id ran exactly once; not harmless once formats are compared by
    # re-running the same ids.
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (scratch_dir / "candidate.diff").write_text(candidate_diff, encoding="utf-8")

    # Bind-mount each task test file into the project before the diff is applied.
    test_mounts: list[tuple[Path, str]] = [
        ((tests_dir / Path(tf).name).resolve(), tf) for tf in task.test_files
    ]

    env: dict[str, str] = {
        "TEST_COMMAND": project.test_command,
        "RUN_BUILD": "1" if project.run_build else "0",
        "BUILD_COMMAND": project.build_command,
        "TASK_TEST_PATTERN": _derive_test_pattern(task.test_files),
        "EDIT_FORMAT": output_format,
        **project.test_env,
        **project.extra_docker_env,
    }

    container_name = _sanitize_container_name(candidate_id)
    argv = _build_docker_run_argv(
        image_tag=project.image_tag,
        container_name=container_name,
        settings=harness_settings,
        scratch_dir=scratch_dir,
        output_dir=output_dir,
        test_mounts=test_mounts,
        env=env,
    )

    start = time.perf_counter()
    returncode, stdout, stderr, timed_out = await run_subprocess_with_timeout(
        argv,
        timeout_s=timeout_used_ms / 1000,
        kill_cmd=["docker", "kill", container_name],
    )
    duration_ms = (time.perf_counter() - start) * 1000

    stage = classify_stage(output_dir, timed_out, project.run_build)
    exit_code = None if timed_out else _read_exit_code(output_dir, returncode)

    result = HarnessResult(
        task_id=task.task_id,
        candidate_id=candidate_id,
        condition=condition,
        model=model,
        stage=stage,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_ms=duration_ms,
        timeout_used_ms=timeout_used_ms,
        stage_detail=read_stage_detail(output_dir, stage),
        apply_mode=read_apply_mode(output_dir, stage),
        apply_reason=read_apply_reason(output_dir),
    )

    _write_harness_result(result, run_id, results_dir=results_dir)
    return result
