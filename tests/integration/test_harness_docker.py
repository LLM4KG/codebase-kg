"""Real-Docker integration tests for the evaluation harness.

Marked @pytest.mark.docker. Self-skips if no Docker daemon is available, so
`pytest -m "not docker"` is the explicit opt-out. Building the pilot image
involves a multi-minute `npm ci`; keep this to 1-2 real tests — the mocked
unit tests already cover the full stage matrix.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from src.config import Settings
from src.harness.docker_build import build_image
from src.harness.models import HarnessStage
from src.harness.runner import run_candidate
from src.harness.tasks import load_pilot_task

pytestmark = pytest.mark.docker

REPO_ROOT = Path(__file__).resolve().parents[2]
RSC_REPO = Path("~/Study/Implementation/sample-projects/small/react-shopping-cart").expanduser()


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return subprocess.run(
            ["docker", "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode == 0
    except Exception:
        return False


@pytest.fixture(scope="session")
def rsc_image():
    if not _docker_available():
        pytest.skip("Docker not available")
    if not RSC_REPO.exists():
        pytest.skip(f"Sample project not found: {RSC_REPO}")

    settings = Settings.load(REPO_ROOT / "pipeline.toml").harness
    task = load_pilot_task("P1", tasks_dir=REPO_ROOT / "tasks" / "pilot")

    import asyncio

    asyncio.run(
        build_image(
            "react-shopping-cart",
            settings,
            repo_path=RSC_REPO,
            expected_sha=task.git_commit,
        )
    )
    return settings


async def test_reference_patch_passes(rsc_image, tmp_path):
    settings = rsc_image
    task = load_pilot_task("P1", tasks_dir=REPO_ROOT / "tasks" / "pilot")
    diff = (REPO_ROOT / "tasks" / "pilot" / "patches" / "P1.diff").read_text()

    result = await run_candidate(
        candidate_diff=diff,
        task=task,
        condition="reference",
        model="reference",
        candidate_id="P1_reference",
        run_id="integration",
        settings=settings,
        results_dir=tmp_path / "results",
        tests_dir=REPO_ROOT / "tasks" / "pilot" / "tests",
    )
    assert result.stage == HarnessStage.test_pass, result.stderr


async def test_malformed_diff_fails_to_apply(rsc_image, tmp_path):
    settings = rsc_image
    task = load_pilot_task("P1", tasks_dir=REPO_ROOT / "tasks" / "pilot")
    bad_diff = (
        "diff --git a/does/not/exist.ts b/does/not/exist.ts\n"
        "--- a/does/not/exist.ts\n"
        "+++ b/does/not/exist.ts\n"
        "@@ -1,1 +1,1 @@\n"
        "-nope\n"
        "+nope2\n"
    )
    result = await run_candidate(
        candidate_diff=bad_diff,
        task=task,
        condition="reference",
        model="reference",
        candidate_id="P1_malformed",
        run_id="integration",
        settings=settings,
        results_dir=tmp_path / "results",
        tests_dir=REPO_ROOT / "tasks" / "pilot" / "tests",
    )
    assert result.stage == HarnessStage.diff_apply_fail
