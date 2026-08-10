"""Tests for docker build-context staging + pinned-commit verification."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.harness.docker_build import stage_build_context, verify_pinned_commit


def _mock_git(returncode=0, stdout="", stderr=""):
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


def test_verify_pinned_commit_matches():
    sha = "9fa56244d0f0c0d363cab744a3305c50eabc08cb"
    with patch(
        "src.harness.docker_build.subprocess.run",
        return_value=_mock_git(stdout=sha + "\n"),
    ):
        verify_pinned_commit(Path("/repo"), sha)  # no raise


def test_verify_pinned_commit_mismatch_raises():
    with patch(
        "src.harness.docker_build.subprocess.run",
        return_value=_mock_git(stdout="deadbeef\n"),
    ):
        with pytest.raises(ValueError, match="Pinned commit mismatch"):
            verify_pinned_commit(Path("/repo"), "9fa56244d0f0c0d363cab744a3305c50eabc08cb")


def test_verify_pinned_commit_git_failure_raises():
    with patch(
        "src.harness.docker_build.subprocess.run",
        return_value=_mock_git(returncode=128, stderr="not a git repo"),
    ):
        with pytest.raises(RuntimeError, match="git rev-parse failed"):
            verify_pinned_commit(Path("/repo"), "abc")


def test_stage_build_context_excludes_vcs_and_deps(tmp_path: Path):
    # Synthetic repo tree.
    src = tmp_path / "src_repo"
    (src / "src").mkdir(parents=True)
    (src / ".git").mkdir()
    (src / "node_modules" / "pkg").mkdir(parents=True)
    (src / "build").mkdir()
    (src / "src" / "App.tsx").write_text("export const App = () => null;")
    (src / "package.json").write_text("{}")
    (src / ".git" / "HEAD").write_text("ref: refs/heads/main")
    (src / "node_modules" / "pkg" / "index.js").write_text("module.exports={}")

    ctx_dir = tmp_path / "ctx"
    staging = stage_build_context("proj", src, ctx_dir)

    assert staging == ctx_dir / "proj"
    assert (staging / "src" / "App.tsx").exists()
    assert (staging / "package.json").exists()
    assert not (staging / ".git").exists()
    assert not (staging / "node_modules").exists()
    assert not (staging / "build").exists()
    # Shared entrypoint staged into the context.
    assert (staging / "docker" / "entrypoint.sh").exists()


def test_stage_build_context_overwrites_existing(tmp_path: Path):
    src = tmp_path / "repo"
    (src).mkdir()
    (src / "a.txt").write_text("new")

    ctx_dir = tmp_path / "ctx"
    stale = ctx_dir / "proj"
    stale.mkdir(parents=True)
    (stale / "old.txt").write_text("stale")

    staging = stage_build_context("proj", src, ctx_dir)
    assert (staging / "a.txt").exists()
    assert not (staging / "old.txt").exists()
