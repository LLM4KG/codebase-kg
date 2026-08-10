"""Unit tests for the unified-diff extractor."""

from __future__ import annotations

from src.generation.diff_extractor import extract_unified_diff

_DIFF = (
    "diff --git a/src/x.ts b/src/x.ts\n"
    "--- a/src/x.ts\n"
    "+++ b/src/x.ts\n"
    "@@ -1,2 +1,2 @@\n"
    "-const a = 1;\n"
    "+const a = 2;\n"
    " export default a;\n"
)


def test_fenced_diff_block():
    resp = f"Here is the fix:\n\n```diff\n{_DIFF}```\n\nDone."
    assert extract_unified_diff(resp) == _DIFF


def test_fenced_patch_language_tag():
    resp = f"```patch\n{_DIFF}```"
    assert extract_unified_diff(resp) == _DIFF


def test_untagged_fence_with_diff_body():
    resp = f"```\n{_DIFF}```"
    assert extract_unified_diff(resp) == _DIFF


def test_bare_unfenced_diff():
    resp = f"I'll change it.\n\n{_DIFF}"
    assert extract_unified_diff(resp) == _DIFF


def test_no_diff_returns_empty():
    assert extract_unified_diff("Sorry, I cannot complete this task.") == ""


def test_empty_input_returns_empty():
    assert extract_unified_diff("") == ""


def test_first_of_multiple_blocks_wins():
    other = "diff --git a/b b/b\n--- a/b\n+++ b/b\n@@ -1 +1 @@\n-x\n+y\n"
    resp = f"```diff\n{_DIFF}```\nand also\n```diff\n{other}```"
    assert extract_unified_diff(resp) == _DIFF


def test_crlf_normalized_to_lf():
    crlf = _DIFF.replace("\n", "\r\n")
    resp = f"```diff\r\n{crlf}```"
    assert extract_unified_diff(resp) == _DIFF


def test_hunk_body_preserved_byte_exact():
    # Leading +/-/space and interior whitespace must survive untouched.
    body = (
        "diff --git a/f b/f\n"
        "--- a/f\n"
        "+++ b/f\n"
        "@@ -1,3 +1,3 @@\n"
        "-  old  \n"
        "+  new  \n"
        "   context  \n"
    )
    resp = f"```diff\n{body}```"
    assert extract_unified_diff(resp) == body


def test_prefers_diff_tag_over_other_fence():
    noise = "```js\nconsole.log('hi')\n```\n"
    resp = f"{noise}```diff\n{_DIFF}```"
    assert extract_unified_diff(resp) == _DIFF


class TestOrphanGitHeaderRepair:
    """A model opening with ```diff sometimes continues the header from the fence
    tag, emitting "--git a/x b/x" for "diff --git a/x b/x". Seen in 18/30
    candidates in the 2026-07-23 claude_primary leg."""

    def test_repairs_orphan_header(self):
        out = extract_unified_diff(
            "```diff\n--git a/src/x.ts b/src/x.ts\n--- a/src/x.ts\n"
            "+++ b/src/x.ts\n@@ -1 +1 @@\n-a\n+b\n```"
        )
        assert out.startswith("diff --git a/src/x.ts b/src/x.ts\n")

    def test_leaves_correct_header_alone(self):
        out = extract_unified_diff(
            "```diff\ndiff --git a/src/x.ts b/src/x.ts\n--- a/src/x.ts\n"
            "+++ b/src/x.ts\n@@ -1 +1 @@\n-a\n+b\n```"
        )
        assert out.startswith("diff --git a/src/x.ts b/src/x.ts\n")
        assert "diff diff" not in out

    def test_does_not_touch_removal_lines(self):
        """`--git ...` inside a hunk body is a removed line, not a header."""
        body = "```diff\ndiff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n---git a b c\n+ok\n```"
        out = extract_unified_diff(body)
        assert "---git a b c" in out
