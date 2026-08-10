"""Generator output formats — how the model is asked to express a code edit.

Phase 1a's pilot ran one format: line-numbered unified diffs. Strict `git apply`
succeeded **0/30**, and 28 of those 30 failures were `error: corrupt patch at
line N` — hunk-header arithmetic, nothing else. That bookkeeping carries no
information and the model gets it wrong almost every time, so the format itself
became an experimental variable rather than a fixed cost.

This package makes it a real, switchable axis (`[run.generation] output_format`)
so the alternative stays runnable and the choice can be defended with measured
numbers instead of an argument.

Three formats, one contract each:

    unified_diff  — the incumbent. `git apply` with the three-tier ladder.
    search_replace— exact-match SEARCH/REPLACE blocks. No line arithmetic, and
                    no lenient tier: a non-unique match fails loudly.
    whole_file    — complete file bodies. No matching at all, so nothing can be
                    mis-placed; the corresponding risk is silent *elision*.

Every extractor obeys the contract established by `extract_unified_diff`:
**it never raises.** An unparseable response yields an empty script, which the
harness classifies as `diff_apply_fail` — a real experimental outcome, not an
error. A format that raised would turn a model's bad day into a pipeline crash.

`unified_diff` is applied by `git apply` inside the container; the other two are
applied by `docker/apply_edits.js` (Node, because only one of the two harness
images ships python3). Both paths end by writing `applied.patch` via `git diff`,
so every candidate yields a canonical unified diff artifact whatever format
produced it — that is what keeps the three arms comparable to each other and to
patch-based prior work.
"""

from __future__ import annotations

from src.generation.edit_formats.base import (
    DEFAULT_FORMAT,
    EditFormat,
    EditScript,
    FileEdit,
    get_edit_format,
    known_formats,
)

__all__ = [
    "DEFAULT_FORMAT",
    "EditFormat",
    "EditScript",
    "FileEdit",
    "get_edit_format",
    "known_formats",
]
