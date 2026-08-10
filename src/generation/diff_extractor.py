"""Pull a unified diff out of a generator LLM response.

The generation instruction (`prompts/generation/generation_instruction.jinja2`)
asks the model to emit exactly one ```diff fenced block and nothing else. Real
models don't always comply, so this extractor degrades gracefully:

    1. First ```diff / ```patch fenced block.
    2. First fenced block whose body already looks like a diff.
    3. A bare `diff --git ... EOF` span with no fences.
    4. Otherwise "" — an empty diff is a real experimental outcome (the harness
       classifies it as diff_apply_fail); this function never raises.
"""

from __future__ import annotations

import re

# ```lang\n<body>\n``` — lang optional; body captured non-greedily.
_FENCE_RE = re.compile(
    r"```[ \t]*([A-Za-z0-9_+-]*)[ \t]*\r?\n(.*?)```",
    re.DOTALL,
)

_DIFF_HEADS = ("diff --git ", "--- ", "+++ ", "Index: ")


def _looks_like_diff(text: str) -> bool:
    head = text.lstrip()
    return head.startswith(_DIFF_HEADS)


# A model that opens its fence with ```diff sometimes continues the *header* from
# the fence tag, emitting "--git a/x b/x" where "diff --git a/x b/x" was meant.
# Observed in 18 of 30 candidates in the 2026-07-23 claude_primary leg.
# Cosmetic in practice — git falls back to the ---/+++ lines, and repairing it
# does not change any apply outcome (verified) — but it makes saved artefacts
# read as malformed, so repair it at the boundary.
_ORPHAN_GIT_HEADER_RE = re.compile(r"^--git (?=\S+ \S+$)", re.MULTILINE)


def _repair_orphan_git_header(diff: str) -> str:
    return _ORPHAN_GIT_HEADER_RE.sub("diff --git ", diff)


def _normalize(diff: str) -> str:
    """Normalize line endings and outer whitespace; keep hunk bodies byte-exact."""
    diff = diff.replace("\r\n", "\n").replace("\r", "\n")
    diff = _repair_orphan_git_header(diff)
    diff = diff.strip("\n")
    if not diff:
        return ""
    return diff + "\n"


def extract_unified_diff(response_text: str) -> str:
    """Return the unified-diff body from an LLM response, or "" if none is found."""
    if not response_text:
        return ""

    blocks = [(lang.lower(), body) for lang, body in _FENCE_RE.findall(response_text)]

    # 1. First explicitly diff/patch-tagged fence.
    for lang, body in blocks:
        if lang in ("diff", "patch"):
            return _normalize(body)

    # 2. First fence whose body already looks like a diff.
    for _lang, body in blocks:
        if _looks_like_diff(body):
            return _normalize(body)

    # 3. Bare, unfenced `diff --git ... EOF`.
    m = re.search(r"diff --git .*", response_text, re.DOTALL)
    if m:
        return _normalize(m.group(0))

    return ""
