"""Tests for configuration loading."""

import pytest

from src.config import get_settings, Settings


class TestConfig:
    def test_default_settings(self):
        settings = get_settings()
        assert settings.llm.temperature == 0.0
        assert settings.llm.concurrency >= 1
        assert settings.db.uri == "bolt://localhost:7687"

    def test_model_default(self):
        settings = get_settings()
        assert settings.llm.model is not None
        assert len(settings.llm.model) > 0

    def test_pipeline_defaults(self):
        settings = get_settings()
        assert settings.pipeline.raw_output_dir is not None


class TestEnvOverridesToml:
    """Documented precedence (CLAUDE.md): CLI > env vars > TOML > defaults.

    Regression: `Settings.load()` passes pipeline.toml values as init kwargs, and
    pydantic-settings ranks init ABOVE env by default — so every key present in the
    TOML silently ignored its environment variable, including PIPELINE_LLM__MODEL,
    the swap the model-agnostic comparison experiments depend on.
    """

    def _toml(self, tmp_path):
        p = tmp_path / "pipeline.toml"
        p.write_text(
            '[llm]\nmodel = "from-toml"\nconcurrency = 1\ncall_delay = 20.0\n'
            '\n[db]\nuri = "bolt://from-toml:7687"\n',
            encoding="utf-8",
        )
        return p

    def test_env_overrides_key_present_in_toml(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PIPELINE_LLM__MODEL", "from-env")
        s = Settings.load(self._toml(tmp_path))
        assert s.llm.model == "from-env"

    def test_toml_wins_over_default_when_no_env(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PIPELINE_LLM__MODEL", raising=False)
        s = Settings.load(self._toml(tmp_path))
        assert s.llm.model == "from-toml"

    def test_sibling_toml_keys_survive_an_override(self, tmp_path, monkeypatch):
        """Env must deep-merge into the section, not replace it wholesale."""
        monkeypatch.setenv("PIPELINE_LLM__MODEL", "from-env")
        s = Settings.load(self._toml(tmp_path))
        assert s.llm.call_delay == 20.0
        assert s.llm.concurrency == 1

    def test_override_across_sections(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PIPELINE_DB__URI", "bolt://from-env:7687")
        s = Settings.load(self._toml(tmp_path))
        assert s.db.uri == "bolt://from-env:7687"
        assert s.llm.model == "from-toml"

    def test_phase2_call_delay_is_overridable(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PIPELINE_LLM__PHASE2_CALL_DELAY", "2.5")
        s = Settings.load(self._toml(tmp_path))
        assert s.llm.phase2_call_delay == 2.5

    def test_nested_project_tables_still_parse(self, tmp_path, monkeypatch):
        """Sections are now passed as dicts, not pre-built models — the dict->model
        coercion for [projects.*] and [harness.projects.*] must still work."""
        p = tmp_path / "pipeline.toml"
        p.write_text(
            '[projects.demo]\nrepo_path = "small/demo"\nexclude_paths = ["src/server"]\n'
            '\n[harness]\nresults_dir = "hr"\n'
            '\n[harness.projects.demo]\nimage_tag = "t:1"\ndockerfile = "d/Dockerfile"\n'
            'node_version = "18"\nrun_build = true\n',
            encoding="utf-8",
        )
        monkeypatch.delenv("PIPELINE_HARNESS__RESULTS_DIR", raising=False)
        s = Settings.load(p)
        assert s.projects["demo"].repo_path == "small/demo"
        assert s.projects["demo"].exclude_paths == ["src/server"]
        assert s.harness.projects["demo"].image_tag == "t:1"
        assert s.harness.projects["demo"].run_build is True
        assert s.harness.results_dir == "hr"
