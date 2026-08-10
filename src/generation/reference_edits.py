"""Render a task's reference patch in each output format, for the mock generator.

`--mock` exists so the whole pipeline — extractor, applier, entrypoint, stage
classification — can be exercised offline with zero tokens and no API key. It
does that by feeding the generator's *reference* answer back through the real
downstream path. With one output format that was a two-line canned string; with
three it needs the reference expressed three ways.

So this module converts a unified diff into SEARCH/REPLACE blocks and into whole
files, reading the pre-patch sources off disk. **Mock and test use only.** It is
never in the path of a real generation — a real candidate's edits come from the
model, and a converter that silently repaired them would defeat the measurement
the format comparison exists to make.

The conversion is exact rather than clever: a hunk already *is* a search/replace
pair (its non-`+` lines are the before, its non-`-` lines are the after), so no
fuzzy matching is involved anywhere.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_HUNK_HEADER_RE = re.compile(
    r"^@@ -\d+(?:,(?P<old>\d+))? \+\d+(?:,(?P<new>\d+))? @@"
)


@dataclass
class _Hunk:
    before: list[str] = field(default_factory=list)
    after: list[str] = field(default_factory=list)
    # Line counts from the `@@` header. The hunk body is bounded by these rather
    # than by "until something that isn't +/-/space", because the blank line at
    # the end of a patch file is indistinguishable from a context line for an
    # empty source line — and swallowing it appends a phantom newline that makes
    # the SEARCH text match nothing.
    old_count: int = -1
    new_count: int = -1

    @property
    def complete(self) -> bool:
        return (
            self.old_count >= 0
            and self.new_count >= 0
            and len(self.before) >= self.old_count
            and len(self.after) >= self.new_count
        )


@dataclass
class _FilePatch:
    path: str
    is_new: bool = False
    is_delete: bool = False
    hunks: list[_Hunk] = field(default_factory=list)


def _strip_prefix(path: str) -> str:
    return re.sub(r"^[ab]/", "", path.strip())


def parse_unified_diff(diff_text: str) -> list[_FilePatch]:
    """Parse a well-formed unified diff into per-file hunks.

    Only handles diffs this project produces or ships as reference patches —
    no renames, no binary, no mode changes. It is not a general patch parser and
    should not be pressed into service as one.
    """
    files: list[_FilePatch] = []
    current: _FilePatch | None = None
    hunk: _Hunk | None = None

    for line in diff_text.replace("\r\n", "\n").split("\n"):
        if line.startswith("diff --git "):
            parts = line.split()
            current = _FilePatch(path=_strip_prefix(parts[-1]))
            files.append(current)
            hunk = None
            continue

        if line.startswith("--- "):
            if current is None:
                current = _FilePatch(path="")
                files.append(current)
            if line[4:].strip() == "/dev/null":
                current.is_new = True
            hunk = None
            continue

        if line.startswith("+++ "):
            if current is None:
                continue
            target = line[4:].strip()
            if target == "/dev/null":
                current.is_delete = True
            elif not current.path:
                current.path = _strip_prefix(target)
            hunk = None
            continue

        header = _HUNK_HEADER_RE.match(line)
        if header:
            if current is None:
                continue
            # A `@@ -5 +5 @@` header with no comma means a one-line side.
            hunk = _Hunk(
                old_count=int(header.group("old") or 1),
                new_count=int(header.group("new") or 1),
            )
            current.hunks.append(hunk)
            continue

        if hunk is None or current is None:
            continue

        if hunk.complete:
            hunk = None
            continue

        if line.startswith("+"):
            hunk.after.append(line[1:])
        elif line.startswith("-"):
            hunk.before.append(line[1:])
        elif line.startswith("\\"):
            continue                       # "\ No newline at end of file"
        else:
            # Context line. A bare "" is a context line for an empty source line
            # — git strips the trailing space on those.
            text = line[1:] if line.startswith(" ") else line
            hunk.before.append(text)
            hunk.after.append(text)

    return [f for f in files if f.path]


def _join(lines: list[str]) -> str:
    return "".join(f"{line}\n" for line in lines)


def to_search_replace(diff_text: str) -> str:
    """Render a unified diff as SEARCH/REPLACE blocks."""
    out: list[str] = []
    for patch in parse_unified_diff(diff_text):
        if patch.is_delete:
            out.append(f">>> DELETE {patch.path}")
            out.append("")
            continue
        for hunk in patch.hunks:
            out.append(patch.path)
            out.append("<<<<<<< SEARCH")
            # A new file has no `before` at all, which is exactly the empty-SEARCH
            # create form the format defines.
            out.append(_join(hunk.before).rstrip("\n") if hunk.before else "")
            out.append("=======")
            out.append(_join(hunk.after).rstrip("\n"))
            out.append(">>>>>>> REPLACE")
            out.append("")
    body = "\n".join(out).strip("\n")
    return f"```text\n{body}\n```\n"


def to_whole_file(diff_text: str, repo_root: str | Path) -> str:
    """Render a unified diff as complete file bodies, read from `repo_root`.

    Raises `FileNotFoundError` if a modified file is missing — for the mock that
    is a real misconfiguration (wrong repo checked out), not a model outcome, so
    it should be loud.
    """
    repo = Path(repo_root)
    out: list[str] = []

    for patch in parse_unified_diff(diff_text):
        if patch.is_delete:
            out.append(f">>> DELETE {patch.path}")
            out.append("")
            continue

        if patch.is_new:
            body = "".join(_join(h.after) for h in patch.hunks)
        else:
            source_path = repo / patch.path
            if not source_path.exists():
                raise FileNotFoundError(
                    f"reference patch modifies {patch.path}, which is not in {repo}"
                )
            body = source_path.read_text(encoding="utf-8")
            for hunk in patch.hunks:
                search, replace = _join(hunk.before), _join(hunk.after)
                if search not in body:
                    raise ValueError(
                        f"reference hunk for {patch.path} does not match the checkout — "
                        "the repo is not at the task's pinned commit"
                    )
                body = body.replace(search, replace, 1)

        suffix = Path(patch.path).suffix.lstrip(".") or "text"
        out.append(patch.path)
        out.append(f"```{suffix}")
        out.append(body.rstrip("\n"))
        out.append("```")
        out.append("")

    return "\n".join(out).strip("\n") + "\n"


def render_reference_response(
    diff_text: str, output_format: str, repo_root: str | Path
) -> str:
    """The canned generator response for a reference patch in `output_format`."""
    if output_format == "unified_diff":
        return f"```diff\n{diff_text.rstrip(chr(10))}\n```\n"
    if output_format == "search_replace":
        return to_search_replace(diff_text)
    if output_format == "whole_file":
        return to_whole_file(diff_text, repo_root)
    raise ValueError(f"Unknown output_format {output_format!r}")
