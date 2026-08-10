"""Tests for [harness] config loading."""

from __future__ import annotations

from pathlib import Path

from src.config import HarnessSettings, ProjectHarnessConfig, Settings

TOML_WITH_HARNESS = """
[harness]
default_timeout_ms = 90000
memory_limit = "2g"
cpu_limit = 1.5
network_mode = "none"
results_dir = "my_results"
work_dir = ".cache/runs"
docker_context_dir = ".cache/ctx"

[harness.projects.react-shopping-cart]
image_tag = "img/rsc:pilot"
dockerfile = "docker/react-shopping-cart/Dockerfile"
node_version = "14.17.3"
run_build = false
test_command = "npm test -- --testPathPattern=$TASK_TEST_PATTERN"
test_env = { CI = "true" }

[harness.projects.takenote]
image_tag = "img/tn:pilot"
dockerfile = "docker/takenote/Dockerfile"
node_version = "14.17.3"
run_build = true
build_command = "npm run build"
test_command = "npx jest"
test_env = {}
"""


def _write_toml(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "pipeline.toml"
    p.write_text(body)
    return p


def test_harness_section_parses(tmp_path: Path):
    settings = Settings.load(_write_toml(tmp_path, TOML_WITH_HARNESS))
    h = settings.harness
    assert isinstance(h, HarnessSettings)
    assert h.default_timeout_ms == 90000
    assert h.memory_limit == "2g"
    assert h.cpu_limit == 1.5
    assert h.results_dir == "my_results"

    rsc = h.projects["react-shopping-cart"]
    assert isinstance(rsc, ProjectHarnessConfig)
    assert rsc.image_tag == "img/rsc:pilot"
    assert rsc.run_build is False
    assert rsc.test_env == {"CI": "true"}
    assert rsc.build_command == "npm run build"  # default

    tn = h.projects["takenote"]
    assert tn.run_build is True
    assert tn.build_command == "npm run build"
    assert tn.test_env == {}


def test_absent_harness_section_falls_back_to_defaults(tmp_path: Path):
    settings = Settings.load(_write_toml(tmp_path, "[llm]\nmodel = \"x\"\n"))
    assert settings.harness.default_timeout_ms == 60_000
    assert settings.harness.memory_limit == "4g"
    assert settings.harness.network_mode == "none"
    assert settings.harness.projects == {}


def test_load_does_not_mutate_toml_projects(tmp_path: Path):
    # `dict(...)` copy before `.pop("projects")` must not corrupt reloads.
    path = _write_toml(tmp_path, TOML_WITH_HARNESS)
    first = Settings.load(path)
    second = Settings.load(path)
    assert set(first.harness.projects) == set(second.harness.projects)
