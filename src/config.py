"""Pipeline configuration using Pydantic Settings with TOML + env layering."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


class ProjectExtractionConfig(BaseModel):
    """Per-project extraction overrides."""
    repo_path: str
    exclude_paths: list[str] = []
    include_paths: list[str] = []
    aliases: dict[str, str] = {}
    # TypeScript/webpack `baseUrl`: the directory bare specifiers resolve against,
    # e.g. base_url = "src" makes `import { useCart } from 'contexts/cart-context'`
    # mean `src/contexts/cart-context`. Distinct from `aliases`, which map a named
    # prefix; baseUrl has no prefix to match on, so alias resolution cannot cover it.
    # Empty means the project uses only relative and aliased imports.
    base_url: str = ""


class ProjectHarnessConfig(BaseModel):
    """Per-project harness (evaluation) overrides."""
    image_tag: str
    dockerfile: str
    node_version: str
    run_build: bool = False
    build_command: str = "npm run build"
    test_command: str = "npm test"
    test_env: dict[str, str] = {}
    extra_docker_env: dict[str, str] = {}


class HarnessSettings(BaseSettings):
    default_timeout_ms: int = 60_000
    memory_limit: str = "4g"
    cpu_limit: float = 2.0
    network_mode: str = "none"
    results_dir: str = "harness_results"
    work_dir: str = ".cache/harness_runs"
    docker_context_dir: str = ".cache/docker_context"
    projects: dict[str, ProjectHarnessConfig] = Field(default_factory=dict)


def _load_toml_settings(settings: BaseSettings) -> dict[str, Any]:
    """Load settings from pipeline.toml if it exists."""
    toml_path = Path("pipeline.toml")
    if toml_path.exists():
        with open(toml_path, "rb") as f:
            return tomllib.load(f)
    return {}


class LLMSettings(BaseSettings):
    model: str = "anthropic/claude-sonnet-4-5"
    temperature: float = 0.0
    max_retries: int = 3
    concurrency: int = 5
    # Seconds to sleep between LLM calls (rate limit throttle). EXTRACTION ONLY —
    # applied in src/extraction/llm_extractor.py. Phase 2 calls route through
    # src/llm/logger.py; see phase2_call_delay below.
    call_delay: float = 0.0

    # Phase 2 (retrieval + generation) inter-call throttle, applied in
    # src/llm/logger.py. Deliberately a SEPARATE key from call_delay, not a reuse:
    # pipeline.toml sets call_delay = 20.0 for extraction, and routing that into
    # Phase 2 would silently turn a ~3-minute pilot leg into a ~15-minute one.
    #
    # Defaults to 0.0 (unthrottled), which is what the 2026-07-23 pilot legs ran
    # at — 40 candidates hit no provider limits at concurrency 2. Phase 5 is a
    # different regime (~4,200 generations); pick a value from the real provider
    # limits then rather than inheriting one. See docs/decision-log.md.
    phase2_call_delay: float = 0.0


class DBSettings(BaseSettings):
    uri: str = "bolt://localhost:7687"
    user: str = ""
    password: str = ""


class ExtractionSettings(BaseSettings):
    repos_root: str = "~/repos"


class PipelineSettings(BaseSettings):
    cache_dir: str = ".cache/llm"
    checkpoint_db: str = ".cache/checkpoint.db"
    raw_output_dir: str = "graph_export"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PIPELINE_",
        env_nested_delimiter="__",
    )

    llm: LLMSettings = Field(default_factory=LLMSettings)
    db: DBSettings = Field(default_factory=DBSettings)
    extraction: ExtractionSettings = Field(default_factory=ExtractionSettings)
    pipeline: PipelineSettings = Field(default_factory=PipelineSettings)
    projects: dict[str, ProjectExtractionConfig] = Field(default_factory=dict)
    harness: HarnessSettings = Field(default_factory=HarnessSettings)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: Any,
        env_settings: Any,
        dotenv_settings: Any,
        file_secret_settings: Any,
    ) -> tuple[Any, ...]:
        """Env vars override TOML — the precedence CLAUDE.md documents.

        `load()` supplies pipeline.toml values as init kwargs. Pydantic's default
        source order puts init *first*, which silently made env vars ineffective for
        every key present in the TOML — including `PIPELINE_LLM__MODEL`, the model
        swap the model-agnostic comparison experiments rely on. Sources are ordered
        highest-priority first, so env must precede init.
        """
        return (env_settings, dotenv_settings, init_settings, file_secret_settings)

    @classmethod
    def load(cls, toml_path: Path | None = None) -> Settings:
        """Load settings with TOML file as base, env vars override."""
        path = toml_path or Path("pipeline.toml")
        toml_data: dict[str, Any] = {}
        if path.exists():
            with open(path, "rb") as f:
                toml_data = tomllib.load(f)

        # Sections are passed as plain dicts, not pre-built models: a constructed
        # model is opaque to the settings sources and cannot be deep-merged with
        # env-derived values, so env overrides would be dropped for whole sections.
        return cls(
            llm=toml_data.get("llm", {}),
            db=toml_data.get("db", {}),
            extraction=toml_data.get("extraction", {}),
            pipeline=toml_data.get("pipeline", {}),
            projects=toml_data.get("projects", {}),
            harness=toml_data.get("harness", {}),
        )

    def resolve_repo_path(self, repo_path: str) -> Path:
        """Resolve repo_path to an absolute filesystem path.

        Absolute paths are returned as-is. Relative paths are joined
        with extraction.repos_root and expanded via Path.expanduser().
        """
        p = Path(repo_path)
        if p.is_absolute():
            resolved = p.resolve()
        else:
            resolved = (Path(self.extraction.repos_root).expanduser() / repo_path).resolve()

        if not resolved.exists():
            raise FileNotFoundError(
                f"Repository not found: {resolved}"
            )
        if not (resolved / "package.json").exists():
            raise FileNotFoundError(
                f"No package.json in repository: {resolved}"
            )
        return resolved


# Singleton instance
_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings.load()
    return _settings
