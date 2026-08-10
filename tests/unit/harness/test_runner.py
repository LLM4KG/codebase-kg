"""End-to-end tests for run_candidate() with the subprocess layer monkeypatched."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.config import HarnessSettings, ProjectHarnessConfig
from src.harness.models import HarnessStage
from src.harness.runner import run_candidate
from src.harness.tasks import PilotTask

TASK = PilotTask(
    task_id="P1",
    project_id="react-shopping-cart",
    git_commit="9fa56244d0f0c0d363cab744a3305c50eabc08cb",
    task_type="bug_fix",
    test_files=[
        "src/contexts/cart-context/__tests__/P1_decrease_removes_product.test.tsx"
    ],
)


def _make_settings(tmp_path: Path, run_build: bool = False) -> HarnessSettings:
    return HarnessSettings(
        work_dir=str(tmp_path / "runs"),
        docker_context_dir=str(tmp_path / "ctx"),
        network_mode="none",
        memory_limit="4g",
        cpu_limit=2.0,
        projects={
            "react-shopping-cart": ProjectHarnessConfig(
                image_tag="img/rsc:pilot",
                dockerfile="docker/react-shopping-cart/Dockerfile",
                node_version="14.17.3",
                run_build=run_build,
                test_command="npm test -- --testPathPattern=$TASK_TEST_PATTERN",
                test_env={"CI": "true"},
            )
        },
    )


def _fake_subprocess(
    *,
    output_files: dict[str, str],
    returncode,
    timed_out: bool,
    captured_argv: list,
):
    """Build an async stub for run_subprocess_with_timeout.

    Writes the given files into the container output dir (mounted at
    <work_dir>/<candidate_id>/output) to emulate the entrypoint, and records
    the docker argv for assertions.
    """

    async def _stub(argv, timeout_s, kill_cmd=None):
        captured_argv.append(argv)
        # The output bind-mount is the host dir passed with target /harness/output.
        out_dir = None
        for i, tok in enumerate(argv):
            if tok == "-v" and argv[i + 1].endswith(":/harness/output"):
                out_dir = Path(argv[i + 1].split(":/harness/output")[0])
        assert out_dir is not None
        for name, content in output_files.items():
            (out_dir / name).write_text(content)
        return (returncode, "STDOUT", "STDERR", timed_out)

    return _stub


@pytest.mark.parametrize(
    "output_files,returncode,timed_out,expected_stage,expected_exit",
    [
        ({"stage.txt": "diff_apply_fail", "apply.log": ""}, 0, False, HarnessStage.diff_apply_fail, 0),
        ({"stage.txt": "install_fail", "apply.log": "", "install.log": ""}, 0, False, HarnessStage.install_fail, 0),
        ({"stage.txt": "build_fail", "apply.log": "", "build.log": ""}, 0, False, HarnessStage.build_fail, 0),
        ({"stage.txt": "test_fail", "apply.log": "", "exit_code.txt": "1"}, 0, False, HarnessStage.test_fail, 1),
        ({"stage.txt": "test_pass", "apply.log": "", "exit_code.txt": "0"}, 0, False, HarnessStage.test_pass, 0),
        ({"apply.log": "", "test_stdout.log": ""}, None, True, HarnessStage.timeout_at_test, None),
    ],
)
async def test_run_candidate_scenarios(
    tmp_path, monkeypatch, output_files, returncode, timed_out, expected_stage, expected_exit
):
    settings = _make_settings(tmp_path)
    results_dir = tmp_path / "results"
    captured_argv: list = []

    monkeypatch.setattr(
        "src.harness.runner.run_subprocess_with_timeout",
        _fake_subprocess(
            output_files=output_files,
            returncode=returncode,
            timed_out=timed_out,
            captured_argv=captured_argv,
        ),
    )

    result = await run_candidate(
        candidate_diff="dummy diff",
        task=TASK,
        condition="kg_augmented",
        model="anthropic/claude-sonnet-4-5",
        candidate_id="P1_kg_augmented_claude_0",
        run_id="run1",
        settings=settings,
        results_dir=results_dir,
    )

    assert result.stage == expected_stage
    assert result.exit_code == expected_exit
    assert result.timeout_used_ms == settings.default_timeout_ms

    # The result JSON was written before returning.
    written = results_dir / "run1" / "P1_kg_augmented_claude_0.json"
    assert written.exists()
    payload = json.loads(written.read_text())
    assert payload["stage"] == expected_stage.value
    # JSONL index appended too.
    jsonl = (results_dir / "run1" / "results.jsonl").read_text().strip().splitlines()
    assert len(jsonl) == 1


async def test_docker_argv_has_limits_and_mounts(tmp_path, monkeypatch):
    settings = _make_settings(tmp_path)
    captured_argv: list = []
    monkeypatch.setattr(
        "src.harness.runner.run_subprocess_with_timeout",
        _fake_subprocess(
            output_files={"stage.txt": "test_pass", "apply.log": "", "exit_code.txt": "0"},
            returncode=0,
            timed_out=False,
            captured_argv=captured_argv,
        ),
    )

    await run_candidate(
        candidate_diff="d",
        task=TASK,
        condition="baseline",
        model="m",
        candidate_id="cand-1",
        run_id="run1",
        settings=settings,
        results_dir=tmp_path / "results",
    )

    argv = captured_argv[0]
    joined = " ".join(argv)
    assert "--memory=4g" in argv
    assert "--cpus=2.0" in argv
    assert "--network=none" in argv

    # One :ro test mount per task.test_files entry, targeting /app/<test_file>.
    test_mounts = [
        a for a in argv
        if a.endswith(":ro") and "/app/src/contexts/cart-context/__tests__/P1_decrease_removes_product.test.tsx:ro" in a
    ]
    assert len(test_mounts) == len(TASK.test_files) == 1
    # candidate.diff is mounted read-only too.
    assert any("candidate.diff:ro" in a for a in argv)
    # Test pattern + env passed through.
    assert "TASK_TEST_PATTERN=P1_decrease_removes_product" in argv
    assert "CI=true" in argv
    assert "RUN_BUILD=0" in argv
