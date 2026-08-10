"""Jinja2 template rendering for LLM prompts."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

_env: Environment | None = None

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


def _get_env() -> Environment:
    global _env
    if _env is None:
        _env = Environment(
            loader=FileSystemLoader(str(PROMPTS_DIR)),
            autoescape=select_autoescape([]),
            keep_trailing_newline=True,
        )
    return _env


def render_prompt(template_name: str, **kwargs: str) -> str:
    """Render a Jinja2 prompt template with the given variables."""
    env = _get_env()
    template = env.get_template(template_name)
    return template.render(**kwargs)


def list_prompts() -> list[str]:
    """List all available prompt template files."""
    return sorted(p.name for p in PROMPTS_DIR.glob("*.jinja2"))
