"""Unit tests for the reference-patch → format converters used by `--mock`.

These exist so an offline dry run proves a format's plumbing end-to-end before
any tokens are spent on it. The invariant that matters: converting a reference
patch and parsing it back must reproduce the same change the patch describes —
otherwise a green `--mock` run would prove nothing about the real path.
"""

from __future__ import annotations

import pytest

from src.generation.edit_formats import get_edit_format
from src.generation.reference_edits import (
    parse_unified_diff,
    render_reference_response,
    to_search_replace,
    to_whole_file,
)

_DIFF = (
    "diff --git a/src/x.ts b/src/x.ts\n"
    "index 111..222 100644\n"
    "--- a/src/x.ts\n"
    "+++ b/src/x.ts\n"
    "@@ -1,3 +1,3 @@\n"
    " const a = 1\n"
    "-const b = 2\n"
    "+const b = 3\n"
    " const c = 4\n"
)

_NEW_FILE_DIFF = (
    "diff --git a/src/new.ts b/src/new.ts\n"
    "new file mode 100644\n"
    "--- /dev/null\n"
    "+++ b/src/new.ts\n"
    "@@ -0,0 +1,2 @@\n"
    "+export const y = 1\n"
    "+export default y\n"
)


def test_parses_hunks_into_before_and_after():
    (patch,) = parse_unified_diff(_DIFF)
    assert patch.path == "src/x.ts"
    assert patch.hunks[0].before == ["const a = 1", "const b = 2", "const c = 4"]
    assert patch.hunks[0].after == ["const a = 1", "const b = 3", "const c = 4"]


def test_hunk_body_is_bounded_by_the_header_counts():
    """The blank line ending a patch file is indistinguishable from a context
    line for an empty source line. Honouring the `@@` counts is what stops it
    being appended as a phantom trailing newline — which made the SEARCH text
    match nothing at all."""
    (patch,) = parse_unified_diff(_DIFF + "\n\n")
    assert patch.hunks[0].before[-1] == "const c = 4"
    assert len(patch.hunks[0].before) == 3


def test_new_file_diff_has_no_before_lines():
    (patch,) = parse_unified_diff(_NEW_FILE_DIFF)
    assert patch.is_new is True
    assert patch.hunks[0].before == []


def test_search_replace_conversion_round_trips():
    script = get_edit_format("search_replace").extract(to_search_replace(_DIFF))
    assert len(script.edits) == 1
    edit = script.edits[0]
    assert edit.path == "src/x.ts"
    assert edit.search == "const a = 1\nconst b = 2\nconst c = 4\n"
    assert edit.content == "const a = 1\nconst b = 3\nconst c = 4\n"


def test_new_file_converts_to_an_empty_search_create():
    script = get_edit_format("search_replace").extract(to_search_replace(_NEW_FILE_DIFF))
    assert [(e.path, e.op) for e in script.edits] == [("src/new.ts", "write")]
    assert script.edits[0].content == "export const y = 1\nexport default y\n"


def test_whole_file_conversion_reads_the_pre_patch_source(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "x.ts").write_text("const a = 1\nconst b = 2\nconst c = 4\n")

    script = get_edit_format("whole_file").extract(to_whole_file(_DIFF, tmp_path))
    assert [(e.path, e.op) for e in script.edits] == [("src/x.ts", "write")]
    assert script.edits[0].content == "const a = 1\nconst b = 3\nconst c = 4\n"
    assert script.elided is False


def test_whole_file_conversion_is_loud_when_the_checkout_is_wrong(tmp_path):
    """A mock failing here means the repo moved off the task's pinned commit —
    a misconfiguration, not a model outcome, so it must not degrade quietly."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "x.ts").write_text("something else entirely\n")
    with pytest.raises(ValueError, match="pinned commit"):
        to_whole_file(_DIFF, tmp_path)


def test_whole_file_conversion_is_loud_when_the_file_is_missing(tmp_path):
    with pytest.raises(FileNotFoundError, match="src/x.ts"):
        to_whole_file(_DIFF, tmp_path)


@pytest.mark.parametrize("fmt", ["unified_diff", "search_replace", "whole_file"])
def test_render_reference_response_is_parseable_by_its_own_format(fmt, tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "x.ts").write_text("const a = 1\nconst b = 2\nconst c = 4\n")
    text = render_reference_response(_DIFF, fmt, tmp_path)
    script = get_edit_format(fmt).extract(text)
    assert bool(script), f"{fmt} produced an unparseable reference response"
    assert script.malformed_blocks == 0
