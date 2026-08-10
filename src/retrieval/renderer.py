"""Format-pluggable context renderer for generation prompts.

Dispatches to Jinja2 templates based on format_variant. Adding a new
format means dropping a new format_X.jinja2 file — zero code changes.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.retrieval.models import ContextData

GENERATION_TEMPLATES_DIR = Path(__file__).parent.parent.parent / "prompts" / "generation"


class ContextRenderer:
    """Renders retrieval results into prompt context using format-variant templates."""

    VALID_VARIANTS = frozenset({"A", "B", "C", "D", "E", "F"})

    def __init__(self, template_dir: str | Path | None = None) -> None:
        self._template_dir = Path(template_dir) if template_dir else GENERATION_TEMPLATES_DIR
        self._env = Environment(
            loader=FileSystemLoader(str(self._template_dir)),
            autoescape=select_autoescape([]),
            keep_trailing_newline=True,
        )

    def _template_name(self, variant: str) -> str:
        return f"format_{variant.lower()}.jinja2"

    def render(self, format_variant: str, context_data: ContextData) -> str:
        """Render retrieval results using the specified format variant.

        Raises:
            ValueError: If format_variant is not in VALID_VARIANTS.
            FileNotFoundError: If the template file for this variant doesn't exist.
        """
        if format_variant not in self.VALID_VARIANTS:
            raise ValueError(
                f"Invalid format_variant {format_variant!r}. "
                f"Must be one of: {', '.join(sorted(self.VALID_VARIANTS))}"
            )

        template_name = self._template_name(format_variant)
        template_path = self._template_dir / template_name

        if not template_path.exists():
            raise FileNotFoundError(
                f"Format {format_variant} is not yet implemented — "
                f"add {template_path}"
            )

        template = self._env.get_template(template_name)
        return template.render(**context_data.model_dump())
