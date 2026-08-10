"""Stage a cleaned checkout as a Docker build context and build the pilot image.

We COPY a staged, cleaned checkout of the already-pinned sample-projects source
rather than `git clone` inside the Dockerfile: no network dependency, no risk of
silent divergence from upstream history at pilot scale. When Phase 2's `forks/`
infrastructure lands, only `stage_build_context()`'s source path changes; the
Dockerfiles and entrypoint.sh stay untouched.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from src.config import HarnessSettings
from src.harness.process import run_subprocess_with_timeout

# Repo-root shared, project-agnostic harness assets, staged into every build
# context so the Dockerfiles' `COPY docker/<name>` resolves against it.
# Both are COPY'd into the image, never mounted — **rebuild both images after
# changing either one**, or the container keeps running the old copy.
HARNESS_ASSETS = (Path("docker/entrypoint.sh"), Path("docker/apply_edits.js"))

# Generous ceiling for `docker build` (multi-minute npm ci). Not the candidate
# timeout — that is a per-run concern handled in runner.py.
BUILD_TIMEOUT_S = 1800.0


def verify_pinned_commit(repo_path: Path, expected_sha: str) -> None:
    """Assert the local checkout is at the SHA the pilot task pins to.

    Protects against someone moving the local checkout without updating the
    pilot task YAML.
    """
    result = subprocess.run(
        ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git rev-parse failed for {repo_path}: {result.stderr.strip()}"
        )
    actual = result.stdout.strip()
    if actual != expected_sha:
        raise ValueError(
            f"Pinned commit mismatch for {repo_path}: "
            f"expected {expected_sha}, found {actual}. "
            "The local checkout moved without the pilot task YAML being updated."
        )


def stage_build_context(
    project_id: str, repo_path: Path, docker_context_dir: Path
) -> Path:
    """Copy a cleaned checkout into the docker build context directory.

    Excludes VCS/build artifacts that don't belong in the image. Also stages the
    shared entrypoint.sh so the Dockerfile's COPY resolves against the context.
    Returns the staging directory path.
    """
    staging_dir = docker_context_dir / project_id
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    shutil.copytree(
        repo_path,
        staging_dir,
        ignore=shutil.ignore_patterns(
            ".git", "node_modules", "build", "dist", "coverage"
        ),
    )

    # Stage the shared harness assets into <staging>/docker/.
    (staging_dir / "docker").mkdir(parents=True, exist_ok=True)
    for asset in HARNESS_ASSETS:
        shutil.copy2(asset, staging_dir / "docker" / asset.name)

    return staging_dir


async def build_image(
    project_id: str,
    settings: HarnessSettings,
    repo_path: Path,
    expected_sha: str,
) -> str:
    """Verify the pin, stage the context, run `docker build`, return the image tag."""
    project = settings.projects[project_id]

    verify_pinned_commit(repo_path, expected_sha)
    staging_dir = stage_build_context(
        project_id, repo_path, Path(settings.docker_context_dir)
    )

    cmd = [
        "docker", "build",
        "-f", project.dockerfile,
        "-t", project.image_tag,
        str(staging_dir),
    ]
    returncode, stdout, stderr, timed_out = await run_subprocess_with_timeout(
        cmd, timeout_s=BUILD_TIMEOUT_S
    )
    if timed_out:
        raise RuntimeError(f"docker build timed out for {project_id}")
    if returncode != 0:
        raise RuntimeError(
            f"docker build failed for {project_id} (exit {returncode}):\n{stderr}"
        )
    return project.image_tag
