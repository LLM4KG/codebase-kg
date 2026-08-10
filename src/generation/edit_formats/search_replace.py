"""SEARCH/REPLACE blocks — exact-match edits with no line arithmetic.

    src/client/containers/NoteList.tsx
    <<<<<<< SEARCH
    <exact existing lines>
    =======
    <replacement lines>
    >>>>>>> REPLACE

An empty SEARCH body creates the file. `>>> DELETE <path>` on its own line
removes one. Blocks apply in order against the progressively-edited buffer, so
two edits to the same file compose.

**Why this format has no lenient tier.** `git apply` degrades: when context
fails it can be told to place hunks by line number instead, which is how the
pilot's P2 candidates landed 186 lines from their target and produced build
errors that described placement rather than content. A SEARCH block either
matches exactly once or it does not; ambiguity is a hard failure. That is a
stronger guarantee than `git apply`'s context matching, not a weaker one, and it
is why `exact_unique` counts as placement-verified.

The parser is a tolerant line-based state machine. Models fence blocks, fence
the whole response, decorate the path (`**path**`, `` `path` ``, `File: path`),
hang the path off the SEARCH marker, and vary the marker width — all of which are
cosmetic and none of which should cost a candidate its result. Fence lines are
stripped only when *outside* a block, so a fence inside file content survives.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.generation.edit_formats.base import EditScript, FileEdit

_SEARCH_RE = re.compile(r"^<{5,9}\s*SEARCH\s*(?P<path>.*?)\s*$")
_SEPARATOR_RE = re.compile(r"^={5,9}\s*$")
_REPLACE_RE = re.compile(r"^>{5,9}\s*REPLACE\s*$")
_DELETE_RE = re.compile(r"^(?:>{3,9}\s*|\*{3}\s*)?DELETE\s+(?P<path>\S+)\s*$")
_FENCE_RE = re.compile(r"^\s*```")

# A candidate path line: no spaces, and either a slash or an extension. Stops
# prose ("Now update the reducer:") from being mistaken for a filename.
_PATH_RE = re.compile(r"^[\w./@+-]+$")


def _clean_path(line: str) -> str | None:
    """Strip the decoration models put around a path, or return None if it isn't one."""
    text = line.strip()
    text = re.sub(r"^(?:#{1,6}\s*)", "", text)
    text = re.sub(r"^(?:File|Path|In)\s*:\s*", "", text, flags=re.IGNORECASE)
    text = text.strip("*_`").strip()
    text = text.rstrip(":").strip()
    if not text or not _PATH_RE.match(text):
        return None
    if "/" not in text and "." not in text:
        return None
    # `a/src/x.ts` / `b/src/x.ts` — diff-habit prefixes leaking into a path line.
    return re.sub(r"^[ab]/", "", text)


def _join(lines: list[str]) -> str:
    return "".join(f"{line}\n" for line in lines)


def extract_search_replace(response_text: str) -> EditScript:
    """Parse SEARCH/REPLACE blocks from a generator response. Never raises."""
    script = EditScript(format="search_replace")
    if not response_text:
        return script

    text = response_text.replace("\r\n", "\n").replace("\r", "\n")

    state = "outside"
    pending_path: str | None = None   # last path seen outside a block
    block_path: str | None = None     # path owning the block being parsed
    sticky_path: str | None = None    # last path successfully edited
    search: list[str] = []
    replace: list[str] = []

    for line in text.split("\n"):
        if state == "outside":
            if _FENCE_RE.match(line):
                continue
            m = _SEARCH_RE.match(line)
            if m:
                inline = _clean_path(m.group("path")) if m.group("path") else None
                block_path = inline or pending_path or sticky_path
                search, replace = [], []
                state = "search"
                continue
            m = _DELETE_RE.match(line)
            if m:
                path = _clean_path(m.group("path"))
                if path:
                    script.edits.append(FileEdit(path=path, op="delete"))
                    sticky_path = path
                else:
                    script.malformed_blocks += 1
                continue
            if line.strip():
                pending_path = _clean_path(line) or pending_path
            continue

        if state == "search":
            if _SEPARATOR_RE.match(line):
                state = "replace"
                continue
            if _REPLACE_RE.match(line):
                # No `=======`: the block's two halves cannot be told apart.
                script.malformed_blocks += 1
                state, pending_path = "outside", None
                continue
            search.append(line)
            continue

        # state == "replace"
        if _REPLACE_RE.match(line):
            if block_path:
                search_text = _join(search).strip("\n")
                replace_text = _join(replace)
                if search_text:
                    script.edits.append(
                        FileEdit(
                            path=block_path,
                            op="replace",
                            search=_join(search),
                            content=replace_text,
                        )
                    )
                else:
                    # Empty SEARCH — create the file with the replacement body.
                    script.edits.append(
                        FileEdit(path=block_path, op="write", content=replace_text)
                    )
                sticky_path = block_path
            else:
                script.malformed_blocks += 1
            state, pending_path, block_path = "outside", None, None
            continue
        replace.append(line)

    if state != "outside":
        # Response ended mid-block — truncated output, or a marker the model
        # never closed. Either way the edit is unusable.
        script.malformed_blocks += 1

    return script


@dataclass(frozen=True)
class _SearchReplaceFormat:
    name: str = "search_replace"
    instruction_template: str = "generation/instruction_search_replace.jinja2"

    def extract(self, response_text: str) -> EditScript:
        return extract_search_replace(response_text)


FORMAT = _SearchReplaceFormat()
