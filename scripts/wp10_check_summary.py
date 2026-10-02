"""WP10: check that results_summary.md has not drifted from the artifacts it quotes.

`results_summary.md` is the sole input for the writing leg, and it is hand-written prose
around tables copied from the generated artifacts. Nothing regenerates it, so the failure
mode is silent: an artifact is regenerated, the summary keeps the old numbers, and the
paper is written from the stale ones.

This script re-extracts every quoted table from its owning artifact and asserts it appears
verbatim in the summary, then checks the scalars the prose states in sentences rather than
in tables. Read-only: no API, no Docker, no writes.

Run: uv run python scripts/wp10_check_summary.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1] / "docs" / "phase_2" / "ijckg-2026"
SUMMARY = DOCS / "results_summary.md"

# (source artifact, heading or line the table follows) — the same anchors the summary was
# built from. A table is the first contiguous run of `|` lines after the anchor.
BLOCKS = [
    ("wp5_outcomes.md", "## Per model and condition"),
    ("wp5_outcomes.md", "## Per task: passed"),
    ("wp5_outcomes.md", "## Passed, per task (compact)"),
    ("wp12_matched.md", "## Passed, per task — published cap vs matched"),
    ("wp12_matched.md", "## Why the matched arms move"),
    ("wp12_matched_context.md", "| Localisation quality, at comparable budget"),
    ("wp9_cost.md", "## 1. KG construction, per repo"),
    ("wp9_cost.md", "### 4a. Per candidate (cost only)"),
    ("schema_coverage.md", "## Per task"),
    ("wp7_extraction_accuracy.md", "## Headline: LLM-extracted types"),
    ("wp7_extraction_accuracy.md", "### LLM scope by repo and by stratum"),
    ("wp7_extraction_accuracy.md", "## Coverage"),
    ("wp12_anomalies.md", "### What the counterfactual actually says"),
]

# Numbers the summary states in prose. Each must appear in the summary AND be justified by
# a substring of its owning artifact, so a scalar cannot drift in only one of the two.
SCALARS = [
    ("0.0199", "wp9_cost.md", "KG USD per candidate, Claude"),
    ("0.0582", "wp9_cost.md", "BM25 USD per candidate, Claude"),
    ("0.0617", "wp9_cost.md", "dense USD per candidate, Claude"),
    ("158–191", "wp9_cost.md", "Claude break-even range"),
    ("1,522–2,567", "wp9_cost.md", "Qwen break-even range"),
    ("60/60", "wp8_anchor_extraction.md", "classifier task-type accuracy"),
    ("8 of 9", "wp8_anchor_extraction.md", "anchors resolving"),
    ("22 of 32", "schema_coverage.md", "fully representable units"),
    ("28 of 32", "schema_coverage.md", "at least partially representable"),
    ("9 of 52", "wp12_anomalies.md", "per-edit replay passes"),
    ("8 / 12", "wp12_anomalies.md", "corrected retention"),
]


def table_after(text: str, anchor: str) -> str:
    lines = text.splitlines()
    try:
        i = next(n for n, line in enumerate(lines) if anchor in line)
    except StopIteration:
        raise LookupError(f"anchor not found: {anchor!r}")
    j = next(n for n in range(i, len(lines)) if lines[n].startswith("|"))
    k = j
    while k < len(lines) and lines[k].startswith("|"):
        k += 1
    return "\n".join(lines[j:k])


def main() -> None:
    if not SUMMARY.exists():
        sys.exit(f"{SUMMARY} does not exist")
    summary = SUMMARY.read_text(encoding="utf-8")
    failures: list[str] = []

    for src, anchor in BLOCKS:
        path = DOCS / src
        if not path.exists():
            failures.append(f"{src}: missing artifact")
            continue
        try:
            block = table_after(path.read_text(encoding="utf-8"), anchor)
        except LookupError as exc:
            failures.append(f"{src}: {exc}")
            continue
        if block not in summary:
            failures.append(
                f"{src} · {anchor!r}: the table in the artifact is not in results_summary.md "
                f"verbatim — the artifact was regenerated and the summary was not updated"
            )

    for value, src, what in SCALARS:
        if value not in summary:
            failures.append(f"summary is missing the {what} ({value})")
        elif value not in (DOCS / src).read_text(encoding="utf-8"):
            failures.append(f"{src} no longer states the {what} ({value}) the summary quotes")

    # Every relative link in the summary must resolve.
    for target in re.findall(r"\]\(([^)#][^)]*)\)", summary):
        rel = target.split("#")[0]
        if rel and not rel.startswith(("http", "mailto")) and not (DOCS / rel).exists():
            failures.append(f"broken link: {target}")

    if failures:
        print(f"results_summary.md has drifted — {len(failures)} problem(s):", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        sys.exit(1)

    print(f"results_summary.md is consistent with its sources "
          f"({len(BLOCKS)} tables verbatim, {len(SCALARS)} scalars cross-checked, all links resolve)")


if __name__ == "__main__":
    main()
