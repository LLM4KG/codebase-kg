"""Unit tests for the three generator output formats.

The contract every extractor shares is that it **never raises** — a response the
model got wrong is an experimental outcome, not a pipeline error. Most of what
follows is therefore about degrading correctly rather than parsing correctly.
"""

from __future__ import annotations

import json

import pytest

from src.generation.edit_formats import get_edit_format, known_formats
from src.generation.edit_formats.search_replace import extract_search_replace
from src.generation.edit_formats.whole_file import detect_elision, extract_whole_file


# --------------------------------------------------------------------------- #
# Registry                                                                    #
# --------------------------------------------------------------------------- #
def test_every_known_format_resolves_and_has_an_instruction():
    for name in known_formats():
        fmt = get_edit_format(name)
        assert fmt.name == name
        assert fmt.instruction_template.startswith("generation/instruction_")


def test_unknown_format_is_rejected_loudly():
    # Not the "never raises" case: a typo in a config must not silently fall
    # back to a format the run did not ask for.
    with pytest.raises(ValueError, match="Unknown output_format"):
        get_edit_format("sed_script")


@pytest.mark.parametrize("name", known_formats())
def test_extractors_never_raise_on_junk(name):
    fmt = get_edit_format(name)
    for junk in ("", "I cannot help with that.", "```\n```", "<<<<<<< SEARCH", "```tsx\nx"):
        fmt.extract(junk)  # must not raise


# --------------------------------------------------------------------------- #
# search_replace                                                              #
# --------------------------------------------------------------------------- #
_SR = """```text
src/App.tsx
<<<<<<< SEARCH
const a = 1;
=======
const a = 2;
>>>>>>> REPLACE
```"""


def test_search_replace_basic_block():
    script = extract_search_replace(_SR)
    assert len(script.edits) == 1
    edit = script.edits[0]
    assert (edit.path, edit.op) == ("src/App.tsx", "replace")
    assert edit.search == "const a = 1;\n"
    assert edit.content == "const a = 2;\n"


def test_search_replace_empty_search_creates_the_file():
    script = extract_search_replace(
        "src/new.ts\n<<<<<<< SEARCH\n=======\nexport const x = 1\n>>>>>>> REPLACE\n"
    )
    assert [(e.path, e.op) for e in script.edits] == [("src/new.ts", "write")]
    assert script.edits[0].content == "export const x = 1\n"


def test_search_replace_delete_directive():
    script = extract_search_replace(">>> DELETE src/old.ts\n")
    assert [(e.path, e.op) for e in script.edits] == [("src/old.ts", "delete")]


def test_search_replace_path_sticks_across_consecutive_blocks():
    """Models routinely give the path once and then emit several blocks for it."""
    text = (
        "src/App.tsx\n"
        "<<<<<<< SEARCH\na\n=======\nb\n>>>>>>> REPLACE\n"
        "<<<<<<< SEARCH\nc\n=======\nd\n>>>>>>> REPLACE\n"
    )
    script = extract_search_replace(text)
    assert [e.path for e in script.edits] == ["src/App.tsx", "src/App.tsx"]


def test_search_replace_path_on_the_marker_line():
    script = extract_search_replace(
        "<<<<<<< SEARCH src/App.tsx\na\n=======\nb\n>>>>>>> REPLACE\n"
    )
    assert [e.path for e in script.edits] == ["src/App.tsx"]


def test_search_replace_prose_is_not_mistaken_for_a_path():
    script = extract_search_replace(
        "Now update the reducer:\nsrc/App.tsx\n"
        "<<<<<<< SEARCH\na\n=======\nb\n>>>>>>> REPLACE\n"
    )
    assert [e.path for e in script.edits] == ["src/App.tsx"]


def test_search_replace_diff_habit_prefix_is_stripped():
    script = extract_search_replace(
        "a/src/App.tsx\n<<<<<<< SEARCH\na\n=======\nb\n>>>>>>> REPLACE\n"
    )
    assert [e.path for e in script.edits] == ["src/App.tsx"]


def test_search_replace_fence_inside_the_body_survives():
    """Stripping fences unconditionally would corrupt file content containing them."""
    text = (
        "src/doc.ts\n<<<<<<< SEARCH\nconst md = `\n```\n`;\n"
        "=======\nconst md = '';\n>>>>>>> REPLACE\n"
    )
    script = extract_search_replace(text)
    assert "```" in script.edits[0].search


def test_search_replace_missing_separator_is_malformed_not_silent():
    script = extract_search_replace("src/App.tsx\n<<<<<<< SEARCH\na\n>>>>>>> REPLACE\n")
    assert script.edits == []
    assert script.malformed_blocks == 1


def test_search_replace_truncated_response_is_malformed():
    script = extract_search_replace("src/App.tsx\n<<<<<<< SEARCH\na\n=======\nb\n")
    assert script.edits == []
    assert script.malformed_blocks == 1


def test_search_replace_empty_response_is_empty_not_malformed():
    """"Produced nothing" and "produced something unreadable" are different results."""
    script = extract_search_replace("I cannot complete this task.")
    assert script.edits == []
    assert script.malformed_blocks == 0
    assert not script


# --------------------------------------------------------------------------- #
# whole_file                                                                  #
# --------------------------------------------------------------------------- #
def test_whole_file_basic_block():
    script = extract_whole_file("src/App.tsx\n```tsx\nconst a = 1;\n```\n")
    assert [(e.path, e.op) for e in script.edits] == [("src/App.tsx", "write")]
    assert script.edits[0].content == "const a = 1;\n"
    assert script.elided is False


def test_whole_file_path_from_the_fence_info_string():
    script = extract_whole_file("```tsx src/App.tsx\nconst a = 1;\n```\n")
    assert [e.path for e in script.edits] == ["src/App.tsx"]


def test_whole_file_unterminated_fence_is_malformed():
    """A cut-off response would otherwise write a truncated body that builds by luck."""
    script = extract_whole_file("src/App.tsx\n```tsx\nconst a = 1;\n")
    assert script.edits == []
    assert script.malformed_blocks == 1


def test_whole_file_delete_directive():
    script = extract_whole_file(">>> DELETE src/old.ts\n")
    assert [(e.path, e.op) for e in script.edits] == [("src/old.ts", "delete")]


@pytest.mark.parametrize(
    "marker",
    [
        "  // ... rest of the file unchanged",
        "// ... existing code ...",
        "/* ... */",
        "  ...",
        "# ... remainder omitted",
        "// (no other changes)",
    ],
)
def test_elision_markers_are_detected(marker):
    assert detect_elision(f"const a = 1;\n{marker}\nexport default a;\n")


@pytest.mark.parametrize(
    "body",
    [
        "const a = 1;\nexport default a;\n",
        "const spread = { ...rest };\n",           # spread is not an elision
        "type T = Record<string, unknown>;\n",
        "const msg = 'no changes were made';\n",   # a string, not a comment
    ],
)
def test_real_code_is_not_flagged_as_elided(body):
    assert detect_elision(body) == ""


def test_whole_file_elision_marks_the_script_and_keeps_the_edit():
    """Elided bodies still apply — they are quarantined at reporting, not dropped."""
    script = extract_whole_file(
        "src/App.tsx\n```tsx\nconst a = 1;\n// ... rest of the file unchanged\n```\n"
    )
    assert script.elided is True
    assert "rest of the file unchanged" in script.elision_marker
    assert len(script.edits) == 1


# --------------------------------------------------------------------------- #
# Serialisation — the contract with docker/apply_edits.js                     #
# --------------------------------------------------------------------------- #
def test_edit_script_json_shape_matches_the_applier():
    script = extract_search_replace(_SR)
    payload = json.loads(script.to_json())
    assert payload["format"] == "search_replace"
    assert payload["edits"][0].keys() == {"path", "op", "search", "content"}
    assert set(payload) == {"format", "edits", "elided", "elision_marker", "malformed_blocks"}


def test_write_edits_carry_content_but_no_search_key():
    payload = json.loads(extract_whole_file("x.ts\n```ts\na\n```\n").to_json())
    assert payload["edits"][0].keys() == {"path", "op", "content"}


def test_delete_edits_carry_only_a_path():
    payload = json.loads(extract_search_replace(">>> DELETE x.ts\n").to_json())
    assert payload["edits"][0] == {"path": "x.ts", "op": "delete"}


def test_unified_diff_serialises_as_a_raw_patch_not_an_edit_list():
    diff = "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n"
    script = get_edit_format("unified_diff").extract(f"```diff\n{diff}```")
    assert script.raw_patch == diff
    assert script.edits == []
    assert bool(script) is True
