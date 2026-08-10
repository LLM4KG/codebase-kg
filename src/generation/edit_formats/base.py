"""The shared edit-script shape and the format registry.

`EditScript` is the one thing every format produces and the one thing the
in-container applier consumes. Formats differ only in how the model is asked to
write an edit and how that text is parsed back — never in what an edit *is*.

Three operations cover every change the pilot tasks need (and the ones the
frozen task set will need):

    replace — swap an exact span of an existing file for new text
    write   — create a file, or overwrite it wholesale
    delete  — remove a file

`unified_diff` is the exception: git owns both its parsing and its application,
so its script carries the raw patch text and no operations. Keeping it inside
the same registry is still worth it — the generator, the CLI and the harness
then have exactly one code path, and the incumbent stays runnable rather than
becoming a branch everyone forgets to maintain.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal, Protocol

Operation = Literal["replace", "write", "delete"]


@dataclass
class FileEdit:
    """One operation against one file."""

    path: str
    op: Operation
    # `replace` only: the exact existing text to find. Must match once.
    search: str = ""
    # `replace`: the text that takes its place. `write`: the whole new body.
    content: str = ""

    def to_dict(self) -> dict:
        d: dict = {"path": self.path, "op": self.op}
        if self.op == "replace":
            d["search"] = self.search
            d["content"] = self.content
        elif self.op == "write":
            d["content"] = self.content
        return d


@dataclass
class EditScript:
    """A parsed generator response, ready for the container to apply.

    Empty (`not script`) is a legitimate outcome: the model produced nothing
    parseable. The harness records that as `diff_apply_fail` with an
    `apply_reason` of `empty_edit`, which is a result, not a bug.
    """

    format: str
    edits: list[FileEdit] = field(default_factory=list)
    # `unified_diff` only — the raw patch git will apply.
    raw_patch: str = ""
    # `whole_file` only — the model elided part of a file it was told to emit in
    # full ("... rest unchanged"). The body on disk is therefore NOT the file the
    # model intended, and any downstream stage describes truncated code. This is
    # whole-file's analogue of `recount_c0`: it applies cleanly and means nothing.
    elided: bool = False
    elision_marker: str = ""
    # Blocks the parser recognised as an edit attempt but could not read. Kept
    # separate from "no edits at all" so the harness can tell `malformed_blocks`
    # from `empty_edit` — "the model tried and I couldn't parse it" and "the
    # model produced nothing" are different experimental outcomes.
    malformed_blocks: int = 0

    def __bool__(self) -> bool:
        return bool(self.edits or self.raw_patch.strip())

    def to_json(self) -> str:
        return json.dumps(
            {
                "format": self.format,
                "edits": [e.to_dict() for e in self.edits],
                "elided": self.elided,
                "elision_marker": self.elision_marker,
                "malformed_blocks": self.malformed_blocks,
            },
            indent=2,
        )


class EditFormat(Protocol):
    """What every output format must provide."""

    name: str
    instruction_template: str

    def extract(self, response_text: str) -> EditScript:
        """Parse a generator response. NEVER raises; returns an empty script instead."""
        ...


DEFAULT_FORMAT = "unified_diff"


def known_formats() -> tuple[str, ...]:
    return ("unified_diff", "search_replace", "whole_file")


def get_edit_format(name: str) -> EditFormat:
    """Look up a format by name.

    Imported lazily so the three format modules can import `base` without a cycle.
    """
    from src.generation.edit_formats import search_replace, unified_diff, whole_file

    registry: dict[str, EditFormat] = {
        unified_diff.FORMAT.name: unified_diff.FORMAT,
        search_replace.FORMAT.name: search_replace.FORMAT,
        whole_file.FORMAT.name: whole_file.FORMAT,
    }
    try:
        return registry[name]
    except KeyError:
        raise ValueError(
            f"Unknown output_format {name!r}. Known: {', '.join(known_formats())}"
        ) from None
