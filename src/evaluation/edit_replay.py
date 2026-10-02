"""A read-only Python mirror of `docker/apply_edits.js`, for counterfactual analysis.

**`docker/apply_edits.js` is normative.** It is the applier that produced every
published result and it is not modified, wrapped or replaced by anything here.
This module exists to answer one question the applier cannot be asked after the
fact — *which of a candidate's edits would have applied?* — over the 420
candidates already on disk.

The mirror differs from the JS in **exactly one** respect: where the JS records a
failure and aborts the whole script, `simulate()` records a verdict and continues
to the next edit. Everything else is transliterated, including the two behaviours
that are load-bearing and easy to get wrong:

* **the staged body** — a second edit to the same file sees the first edit's
  output, and a *skipped* edit contributes nothing, so the edit after it sees the
  body as it stood before;
* **`locate()`'s single trailing-newline retry** — the one tolerance the format
  allows, and the only normalisation of any kind.

Because a transliteration can drift from its original, nothing here is trusted on
its own. `scripts/wp12_apply_loss_report.py` runs a **differential gate** on
every invocation: the simulator's predicted first failure must equal the
`apply_reason` the harness actually recorded, for every candidate in the corpus.

Why all-or-nothing is right for the harness and wrong for measurement: a
half-applied script produces build errors describing a state the model never
asked for. But it also collapses "three of four edits were correct" into
`never_applied`, which makes a pass count an upper bound on the damage a thin
context did, rather than a measurement of it.
"""

from __future__ import annotations

import json
import posixpath
import re
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable

from src.generation.edit_formats.base import EditScript, FileEdit

# `resolveInRepo` in the JS resolves against this. Mirrored so the path-escape
# check produces the same verdict for the same edit.
REPO = "/app"

SourceReader = Callable[[str], "str | None"]
"""Given a repo-relative path, the file's body in the container, or None if absent."""


# --------------------------------------------------------------------------- #
# The mirror                                                                  #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class EditVerdict:
    """What the applier would have done with one edit, had it reached it."""

    index: int
    path: str
    op: str
    applied: bool
    # The `apply_reason` this edit would have produced. None when it applied.
    reason: str | None = None
    # `replace` only: how many times the SEARCH text was found.
    match_count: int | None = None


@dataclass(frozen=True)
class Simulation:
    verdicts: tuple[EditVerdict, ...]
    # Indices into the original edit list, in order, that would have applied.
    accepted: tuple[int, ...]
    # The `apply_reason` the real all-or-nothing applier would have recorded:
    # the first failure, or None if every edit applied. This is the field the
    # differential gate checks.
    first_failure: str | None
    # True when the script never reached the edit loop at all (no edits).
    script_level: bool = False

    @property
    def would_apply(self) -> bool:
        return self.first_failure is None

    @property
    def partial(self) -> bool:
        """At least one edit would have applied, but the script as a whole failed."""
        return bool(self.accepted) and not self.would_apply


def resolve_in_repo(rel_path: str) -> str | None:
    """Mirror of `resolveInRepo`: None when the path would write outside /app."""
    full = posixpath.normpath(posixpath.join(REPO, rel_path))
    if full != REPO and not full.startswith(REPO + "/"):
        return None
    return full


def count_occurrences(haystack: str, needle: str) -> int:
    """Mirror of `countOccurrences`: non-overlapping, advancing by needle length."""
    if not needle:
        return 0
    count = 0
    index = haystack.find(needle)
    while index != -1:
        count += 1
        index = haystack.find(needle, index + len(needle))
    return count


def locate(body: str, search: str) -> tuple[str, int]:
    """Mirror of `locate`: (needle, count), with the one trailing-newline retry.

    A SEARCH block whose last line is the file's last line arrives carrying a
    newline the file does not have. That is an artefact of how the block was
    written down, not a difference in the code. No other normalisation — an
    approximate match that applies is the failure mode this format exists to
    remove.
    """
    needle = search
    count = count_occurrences(body, needle)
    if count == 0 and needle.endswith("\n"):
        needle = needle[:-1]
        count = count_occurrences(body, needle)
    return needle, count


def simulate(script: EditScript, read_source: SourceReader) -> Simulation:
    """Replay `script` against the pristine tree, recording a verdict per edit.

    Takes the whole `EditScript`, not just its edits, because the JS's empty-script
    branch reads `script.malformed_blocks` to tell "the model produced nothing"
    from "the model tried and the parser could not read it" — two different
    experimental outcomes, and the differential gate checks both.
    """
    if not script.edits:
        reason = "malformed_blocks" if script.malformed_blocks > 0 else "empty_edit"
        return Simulation(verdicts=(), accepted=(), first_failure=reason, script_level=True)

    # relPath -> body, or None for "deleted". Mirrors `staged` in the JS: absent
    # means "not touched yet, read from disk".
    staged: dict[str, str | None] = {}

    def current_body(rel: str) -> str | None:
        if rel in staged:
            return staged[rel]
        return read_source(rel)

    verdicts: list[EditVerdict] = []
    accepted: list[int] = []
    first_failure: str | None = None

    def record(i: int, edit: FileEdit, reason: str | None, count: int | None = None) -> None:
        nonlocal first_failure
        verdicts.append(
            EditVerdict(
                index=i, path=edit.path, op=edit.op,
                applied=reason is None, reason=reason, match_count=count,
            )
        )
        if reason is None:
            accepted.append(i)
        elif first_failure is None:
            first_failure = reason

    for i, edit in enumerate(script.edits):
        rel = edit.path
        if resolve_in_repo(rel) is None:
            record(i, edit, "file_not_found")
            continue

        if edit.op == "delete":
            if current_body(rel) is None:
                record(i, edit, "file_not_found")
                continue
            staged[rel] = None
            record(i, edit, None)
            continue

        if edit.op == "write":
            staged[rel] = edit.content
            record(i, edit, None)
            continue

        if edit.op == "replace":
            body = current_body(rel)
            if body is None:
                record(i, edit, "file_not_found")
                continue
            needle, count = locate(body, edit.search)
            if count == 0:
                record(i, edit, "search_not_found", 0)
                continue
            if count > 1:
                # Deliberately fatal in the JS, and fatal here: picking the first
                # match is exactly the guess `git apply --recount -C0` makes.
                record(i, edit, "ambiguous_match", count)
                continue
            at = body.index(needle)
            staged[rel] = body[:at] + edit.content + body[at + len(needle):]
            record(i, edit, None, 1)
            continue

        record(i, edit, "malformed_blocks")

    return Simulation(
        verdicts=tuple(verdicts), accepted=tuple(accepted), first_failure=first_failure
    )


# --------------------------------------------------------------------------- #
# Reading the tree the container saw                                          #
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=4096)
def source_at_commit(repo_root: str, commit: str, path: str) -> str | None:
    """`git show <commit>:<path>` — the file as the container's /app had it, or None.

    Cached: the corpus replays hundreds of edits against a few dozen files, and
    a subprocess per edit would dominate the runtime. Decoded as UTF-8 exactly as
    Node's `fs.readFileSync(full, 'utf8')` does.
    """
    proc = subprocess.run(
        ["git", "-C", repo_root, "show", f"{commit}:{path}"],
        capture_output=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.decode("utf-8")


def container_source_reader(
    repo_root: Path, commit: str, test_files: dict[str, Path] | None = None
) -> SourceReader:
    """A reader for the tree the harness container actually had at /app.

    That tree is the repo at the pinned commit **plus** each task test file
    bind-mounted over its target path before the applier runs — so a SEARCH
    against a test file would have found it. Rare, but the differential gate
    would report it as a mismatch rather than a finding, so the mount is mirrored.
    """
    mounts = test_files or {}

    def read(rel: str) -> str | None:
        if rel in mounts:
            return mounts[rel].read_text(encoding="utf-8") if mounts[rel].exists() else None
        return source_at_commit(str(repo_root), commit, rel)

    return read


# --------------------------------------------------------------------------- #
# What the model was shown                                                    #
# --------------------------------------------------------------------------- #
# `#### <name> (`<path>`)` — the Target Components headers in
# prompts/generation/format_a.jinja2, which is the `format_variant` every
# condition uses. Related Components render as `**name** (`path`)` with no source
# and are deliberately NOT matched: a props list is not seeing the file.
_HEADER_RE = re.compile(r"^#### .+ \(`(?P<path>[^`]+)`\)\s*$", re.MULTILINE)


def context_files(prompt_text: str) -> frozenset[str]:
    """The repo-relative paths whose source the prompt actually carried.

    Parses the rendered prompt rather than `metadata.json` because `kg_augmented`
    and `whole_file` write no `included_files` key at all — the headers are the
    only record of "what this model was shown" that exists for every condition.
    `floor` renders no context block and correctly yields the empty set.
    """
    return frozenset(m.group("path") for m in _HEADER_RE.finditer(prompt_text))


# --------------------------------------------------------------------------- #
# Scripts on disk                                                             #
# --------------------------------------------------------------------------- #
def load_script(path: Path) -> EditScript:
    """Parse a candidate's `diff.patch` (the JSON edit script) back into an EditScript."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return EditScript(
        format=data["format"],
        edits=[
            FileEdit(
                path=e["path"], op=e["op"],
                search=e.get("search", ""), content=e.get("content", ""),
            )
            for e in data.get("edits", [])
        ],
        elided=data.get("elided", False),
        elision_marker=data.get("elision_marker", ""),
        malformed_blocks=data.get("malformed_blocks", 0),
    )


def reduced_script(original: EditScript, accepted: tuple[int, ...] | list[int]) -> str:
    """The original script with only `accepted` edits, serialised the one way.

    Goes through `EditScript.to_json()` rather than editing the JSON text, so a
    reduction cannot differ from a real script in key order, indentation or which
    optional keys an op carries. Passing every index must reproduce the original
    file byte-for-byte; `scripts/wp12_per_edit_replay.py` asserts exactly that
    before it sends anything to Docker.
    """
    keep = list(accepted)
    if keep != sorted(set(keep)):
        raise ValueError(f"accepted indices must be sorted and distinct: {accepted!r}")
    if keep and (keep[0] < 0 or keep[-1] >= len(original.edits)):
        raise ValueError(f"accepted indices out of range for {len(original.edits)} edits")
    return EditScript(
        format=original.format,
        edits=[original.edits[i] for i in keep],
        elided=original.elided,
        elision_marker=original.elision_marker,
        malformed_blocks=original.malformed_blocks,
    ).to_json()
