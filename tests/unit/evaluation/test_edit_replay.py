"""Tests for the Python mirror of `docker/apply_edits.js`.

Every test here is pinned to a behaviour of the **JS**, not to a behaviour that
seemed reasonable in Python. The mirror's whole value is that it predicts what
the real applier did; a test that only checks internal consistency would pass
while the mirror drifted. Where a behaviour is deliberately harsh — an ambiguous
SEARCH being fatal rather than resolved to the first match — the test says so,
because the obvious "fix" would silently change what 420 published candidates
are measured against.

The corpus-wide differential gate in `scripts/wp12_apply_loss_report.py` is the
other half: these tests pin the mechanics, that gate pins the mirror to the
recorded results.
"""

from __future__ import annotations

import json

import pytest

from src.evaluation.edit_replay import (
    context_files,
    count_occurrences,
    load_script,
    locate,
    reduced_script,
    resolve_in_repo,
    simulate,
)
from src.generation.edit_formats.base import EditScript, FileEdit


def reader(**files: str):
    """A source reader over an in-memory tree; anything absent reads as missing."""
    return lambda rel: files.get(rel)


def script(*edits: FileEdit, malformed: int = 0) -> EditScript:
    return EditScript(format="search_replace", edits=list(edits), malformed_blocks=malformed)


# --------------------------------------------------------------------------- #
# The staged body                                                             #
# --------------------------------------------------------------------------- #
def test_a_second_edit_to_one_file_sees_the_first_edits_output():
    # `staged` in the JS: currentBody() returns the staged body when present, so
    # a SEARCH may match text the previous edit introduced.
    sim = simulate(
        script(
            FileEdit(path="a.ts", op="replace", search="one\n", content="ONE\n"),
            FileEdit(path="a.ts", op="replace", search="ONE\n", content="uno\n"),
        ),
        reader(**{"a.ts": "one\ntwo\n"}),
    )
    assert sim.would_apply
    assert sim.accepted == (0, 1)


def test_a_skipped_edit_contributes_nothing_and_the_next_one_sees_the_old_body():
    # The mirror's single deviation: it continues past a failure. What it must
    # NOT do is stage the failed edit's replacement anyway — the edit after it
    # has to see the body exactly as it stood before.
    sim = simulate(
        script(
            FileEdit(path="a.ts", op="replace", search="absent\n", content="X\n"),
            FileEdit(path="a.ts", op="replace", search="one\n", content="ONE\n"),
        ),
        reader(**{"a.ts": "one\ntwo\n"}),
    )
    assert [v.applied for v in sim.verdicts] == [False, True]
    assert sim.accepted == (1,)
    assert sim.partial


def test_a_failure_cascades_when_the_next_edit_depended_on_it():
    # The converse: an edit whose SEARCH only exists because of an earlier edit
    # fails too. Two lost edits, one root cause — which is why M1 counts
    # candidates with >=1 applying edit rather than summing edits.
    sim = simulate(
        script(
            FileEdit(path="a.ts", op="replace", search="absent\n", content="NEW\n"),
            FileEdit(path="a.ts", op="replace", search="NEW\n", content="NEWER\n"),
        ),
        reader(**{"a.ts": "one\n"}),
    )
    assert sim.accepted == ()
    assert [v.reason for v in sim.verdicts] == ["search_not_found", "search_not_found"]


def test_a_write_then_replace_composes_against_the_written_body():
    sim = simulate(
        script(
            FileEdit(path="new.ts", op="write", content="hello\n"),
            FileEdit(path="new.ts", op="replace", search="hello\n", content="world\n"),
        ),
        reader(),
    )
    assert sim.would_apply


def test_a_replace_after_a_delete_cannot_find_the_file():
    # staged[rel] = null, and currentBody returns it, so the file reads as gone.
    sim = simulate(
        script(
            FileEdit(path="a.ts", op="delete"),
            FileEdit(path="a.ts", op="replace", search="one\n", content="ONE\n"),
        ),
        reader(**{"a.ts": "one\n"}),
    )
    assert [v.reason for v in sim.verdicts] == [None, "file_not_found"]


# --------------------------------------------------------------------------- #
# locate(): the one tolerance                                                 #
# --------------------------------------------------------------------------- #
def test_the_trailing_newline_retry_is_the_only_normalisation():
    # A SEARCH block whose last line is the file's last line carries a newline
    # the file does not have.
    body = "one\ntwo"
    needle, count = locate(body, "two\n")
    assert (needle, count) == ("two", 1)


def test_the_retry_strips_exactly_one_newline_and_no_whitespace():
    assert locate("one\ntwo", "two\n\n")[1] == 0
    assert locate("    indented\n", "indented\n")[1] == 1   # substring, not line-anchored
    assert locate("one\ntwo\n", "  two\n")[1] == 0          # no indentation guessing


def test_an_empty_search_never_matches():
    # countOccurrences returns 0 for an empty needle. The parser routes empty
    # SEARCH blocks to `write`, so this is a guard, not a path anything takes.
    assert count_occurrences("anything", "") == 0


def test_occurrences_are_counted_without_overlap():
    # index += needle.length in the JS, so "aaaa" holds two "aa", not three.
    assert count_occurrences("aaaa", "aa") == 2


# --------------------------------------------------------------------------- #
# Ambiguity is fatal                                                          #
# --------------------------------------------------------------------------- #
def test_two_matches_are_ambiguous_match_and_never_the_first_one():
    # Picking the first match is precisely the guess `git apply --recount -C0`
    # makes, and it is what put P2's hunks 186 lines from their target in the
    # 2026-07-23 leg. If this test ever starts failing because someone "fixed"
    # the mirror to resolve ambiguity, the published pass counts have changed
    # meaning.
    sim = simulate(
        script(FileEdit(path="a.ts", op="replace", search="dup\n", content="X\n")),
        reader(**{"a.ts": "dup\nmiddle\ndup\n"}),
    )
    assert sim.first_failure == "ambiguous_match"
    assert sim.verdicts[0].match_count == 2
    assert sim.accepted == ()


# --------------------------------------------------------------------------- #
# Missing files, escaping paths, unknown ops                                  #
# --------------------------------------------------------------------------- #
def test_replace_and_delete_need_the_file_but_write_creates_it():
    missing = reader()
    assert simulate(script(FileEdit(path="a.ts", op="replace", search="x", content="y")),
                    missing).first_failure == "file_not_found"
    assert simulate(script(FileEdit(path="a.ts", op="delete")), missing).first_failure == "file_not_found"
    assert simulate(script(FileEdit(path="a.ts", op="write", content="y")), missing).would_apply


@pytest.mark.parametrize("path", ["../outside.ts", "/etc/passwd", "src/../../x.ts"])
def test_a_path_that_escapes_the_repo_is_file_not_found(path):
    assert resolve_in_repo(path) is None
    sim = simulate(script(FileEdit(path=path, op="write", content="x")), reader())
    assert sim.first_failure == "file_not_found"


def test_a_path_that_climbs_and_returns_stays_inside():
    assert resolve_in_repo("src/sub/../x.ts") == "/app/src/x.ts"


def test_an_unknown_op_is_a_malformed_block():
    sim = simulate(script(FileEdit(path="a.ts", op="rename")), reader(**{"a.ts": "x"}))
    assert sim.first_failure == "malformed_blocks"


# --------------------------------------------------------------------------- #
# Script-level outcomes                                                       #
# --------------------------------------------------------------------------- #
def test_no_edits_is_empty_edit_but_no_edits_after_a_parse_attempt_is_malformed():
    # "The model produced nothing" and "the model tried and I could not parse it"
    # are different experimental outcomes; the JS reads script.malformed_blocks
    # to tell them apart, so the mirror must take the whole script, not its edits.
    assert simulate(script(), reader()).first_failure == "empty_edit"
    assert simulate(script(malformed=2), reader()).first_failure == "malformed_blocks"
    assert simulate(script(), reader()).script_level


def test_first_failure_is_the_first_one_not_the_last():
    # This is the field the differential gate checks against the recorded
    # apply_reason, and the real applier aborts at the first failure.
    sim = simulate(
        script(
            FileEdit(path="a.ts", op="replace", search="absent\n", content="X\n"),
            FileEdit(path="gone.ts", op="replace", search="y", content="z"),
        ),
        reader(**{"a.ts": "one\n"}),
    )
    assert sim.first_failure == "search_not_found"
    assert [v.reason for v in sim.verdicts] == ["search_not_found", "file_not_found"]


# --------------------------------------------------------------------------- #
# context_files()                                                             #
# --------------------------------------------------------------------------- #
def test_context_files_reads_target_headers_and_ignores_related_components():
    # Related Components render a name, props and hooks but no source. Counting
    # them as "shown" would say a model saw a file whose body it never got.
    prompt = (
        "### Target Components\n\n"
        "#### NoteList (`src/client/containers/NoteList.tsx`)\n\n"
        "```tsx\nconst NoteList = () => null\n```\n\n"
        "### Related Components\n\n"
        "**SearchBar** (`src/client/components/NoteList/SearchBar.tsx`)\n"
        "- Props: searchNotes\n"
    )
    assert context_files(prompt) == frozenset({"src/client/containers/NoteList.tsx"})


def test_context_files_is_empty_for_a_floor_prompt():
    assert context_files("Implement the following change.\n") == frozenset()


# --------------------------------------------------------------------------- #
# Reduction                                                                   #
# --------------------------------------------------------------------------- #
def test_reducing_to_every_index_reproduces_the_original_json():
    original = script(
        FileEdit(path="a.ts", op="replace", search="one\n", content="ONE\n"),
        FileEdit(path="b.ts", op="write", content="x\n"),
        FileEdit(path="c.ts", op="delete"),
    )
    assert reduced_script(original, list(range(3))) == original.to_json()


def test_a_reduction_keeps_order_and_is_a_strict_subset():
    original = script(
        FileEdit(path="a.ts", op="replace", search="1\n", content="A\n"),
        FileEdit(path="b.ts", op="replace", search="2\n", content="B\n"),
        FileEdit(path="c.ts", op="replace", search="3\n", content="C\n"),
    )
    kept = json.loads(reduced_script(original, (0, 2)))["edits"]
    assert [e["path"] for e in kept] == ["a.ts", "c.ts"]
    assert kept == [e.to_dict() for e in (original.edits[0], original.edits[2])]


def test_a_reduction_carries_the_scripts_own_format_and_flags():
    original = EditScript(format="search_replace", edits=[FileEdit(path="a.ts", op="delete")],
                          malformed_blocks=3)
    out = json.loads(reduced_script(original, [0]))
    assert out["format"] == "search_replace" and out["malformed_blocks"] == 3


@pytest.mark.parametrize("bad", [[1, 0], [0, 0], [5]])
def test_unsorted_duplicated_or_out_of_range_indices_are_refused(bad):
    original = script(FileEdit(path="a.ts", op="delete"), FileEdit(path="b.ts", op="delete"))
    with pytest.raises(ValueError):
        reduced_script(original, bad)


def test_an_empty_reduction_is_a_script_the_applier_rejects_as_empty_edit(tmp_path):
    # A candidate with no applying edits has nothing to replay; step 9 must skip
    # it rather than send an empty script to Docker and record a spurious zero.
    original = script(FileEdit(path="a.ts", op="delete"))
    p = tmp_path / "reduced.patch"
    p.write_text(reduced_script(original, []), encoding="utf-8")
    assert simulate(load_script(p), reader()).first_failure == "empty_edit"


def test_load_script_round_trips_a_real_candidates_patch(tmp_path):
    original = script(
        FileEdit(path="a.ts", op="replace", search="one\n", content="ONE\n"),
        FileEdit(path="b.ts", op="write", content="x\n"),
        FileEdit(path="c.ts", op="delete"),
    )
    p = tmp_path / "diff.patch"
    p.write_text(original.to_json(), encoding="utf-8")
    assert load_script(p).to_json() == original.to_json()
