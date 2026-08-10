"""Whole-file output — the complete new body of every file the change touches.

    src/client/containers/NoteMenuBar.tsx
    ```tsx
    <complete file contents>
    ```

`>>> DELETE <path>` removes a file, since a whole-file body cannot express
absence.

**The elision guard is the point of this module.** Whole-file has no placement
to get wrong, which removes the `recount_c0` failure mode — but it introduces an
exactly analogous one: a model told to emit 350 lines writes
`// ... rest of the file unchanged ...` and the applier faithfully truncates the
file. That applies cleanly, builds or fails for reasons unrelated to the model's
intent, and is indistinguishable from a real result unless it is detected. So an
elided body is marked, applied, and reported under `apply_mode =
whole_file_elided`, which sits outside `PLACEMENT_VERIFIED_MODES` alongside
`recount_c0`.

The guard is deliberately biased toward false positives. Quarantining a good
candidate costs one data point; counting a truncated one costs the result's
credibility — the same trade the three-tier apply ladder already makes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.generation.edit_formats.base import EditScript, FileEdit
from src.generation.edit_formats.search_replace import _DELETE_RE, _clean_path

_FENCE_OPEN_RE = re.compile(r"^\s*```+\s*(?P<info>.*?)\s*$")
_FENCE_CLOSE_RE = re.compile(r"^\s*```+\s*$")

# A line that is *nothing but* an ellipsis, optionally wrapped in comment syntax.
_ELLIPSIS_ONLY_RE = re.compile(
    r"^\s*(?://+|/\*+|\*|#+|<!--)?\s*\.{3,}\s*(?:\*/|-->)?\s*$"
)

# A comment line that says, in so many words, that code was left out.
_ELISION_PHRASE_RE = re.compile(
    r"^\s*(?://+|/\*+|\*|#+|<!--)\s*.*?"
    r"(?:\.{3}|…)?\s*"
    r"(?:rest of (?:the )?(?:file|code|component)"
    r"|remains? (?:the same|unchanged)"
    r"|(?:code |lines? )?(?:unchanged|omitted|elided|truncated)"
    r"|existing code"
    r"|no (?:other )?changes?"
    r"|as (?:before|above))",
    re.IGNORECASE,
)


def detect_elision(body: str) -> str:
    """Return the offending line if the body looks elided, else "".

    Checked per line rather than over the whole text so the marker can be quoted
    back in the result — "it was elided" is much less useful than "it said
    `// ... rest of the file unchanged`".
    """
    for line in body.split("\n"):
        if _ELLIPSIS_ONLY_RE.match(line) and line.strip():
            return line.strip()
        if _ELISION_PHRASE_RE.match(line):
            return line.strip()
    return ""


def extract_whole_file(response_text: str) -> EditScript:
    """Parse path + fenced whole-file bodies from a generator response. Never raises."""
    script = EditScript(format="whole_file")
    if not response_text:
        return script

    text = response_text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")

    pending_path: str | None = None
    i = 0
    while i < len(lines):
        line = lines[i]

        m = _DELETE_RE.match(line)
        if m:
            path = _clean_path(m.group("path"))
            if path:
                script.edits.append(FileEdit(path=path, op="delete"))
            else:
                script.malformed_blocks += 1
            i += 1
            continue

        fence = _FENCE_OPEN_RE.match(line)
        if fence:
            # ```tsx src/x.tsx — some models hang the path off the info string.
            info_tokens = fence.group("info").split()
            info_path = None
            for token in reversed(info_tokens):
                info_path = _clean_path(token)
                if info_path:
                    break
            path = info_path or pending_path

            body: list[str] = []
            i += 1
            closed = False
            while i < len(lines):
                if _FENCE_CLOSE_RE.match(lines[i]):
                    closed = True
                    i += 1
                    break
                body.append(lines[i])
                i += 1

            if not closed:
                # Unterminated fence: the response was cut off mid-file. Emitting
                # it would write a truncated body that compiles-or-not by luck.
                script.malformed_blocks += 1
                pending_path = None
                continue
            if not path:
                script.malformed_blocks += 1
                pending_path = None
                continue

            content = "".join(f"{b}\n" for b in body)
            marker = detect_elision(content)
            if marker and not script.elided:
                script.elided = True
                script.elision_marker = marker
            script.edits.append(FileEdit(path=path, op="write", content=content))
            pending_path = None
            continue

        if line.strip():
            pending_path = _clean_path(line) or pending_path
        i += 1

    return script


@dataclass(frozen=True)
class _WholeFileFormat:
    name: str = "whole_file"
    instruction_template: str = "generation/instruction_whole_file.jinja2"

    def extract(self, response_text: str) -> EditScript:
        return extract_whole_file(response_text)


FORMAT = _WholeFileFormat()
