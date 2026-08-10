"""The incumbent format: a single line-numbered unified diff, applied by `git apply`.

Parsing is unchanged — it delegates to `extract_unified_diff`, including its four
graceful fallbacks and the orphan-`--git`-header repair. This module only wraps
that function in the `EditFormat` contract so the incumbent stays selectable
alongside the alternatives rather than becoming a special case in the caller.

Kept runnable deliberately. The 2026-07-23 `claude_primary` leg is the only n=5
measurement of this format, and a thesis comparison that cannot be repeated is
not a comparison.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.generation.diff_extractor import extract_unified_diff
from src.generation.edit_formats.base import EditScript


@dataclass(frozen=True)
class _UnifiedDiffFormat:
    name: str = "unified_diff"
    instruction_template: str = "generation/instruction_unified_diff.jinja2"

    def extract(self, response_text: str) -> EditScript:
        return EditScript(format=self.name, raw_patch=extract_unified_diff(response_text))


FORMAT = _UnifiedDiffFormat()
