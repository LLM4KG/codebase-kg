#!/usr/bin/env python3
"""Cross-check every USES_LIBRARY_HOOK.count in the graph against the raw extractions.

`count` is documented as "number of call-site occurrences within the component"
(schema §2.4) but was hardcoded to 1 on every Stage 3 edge. This verifies the fix
against the source of truth — the per-file LLM outputs on disk — rather than
against a hand-written expectation table.

Two producers write these edges and both are checked:

* **Stage 3** `(:Function_Component)-[:USES_LIBRARY_HOOK]->(:Library_Hook)`, whose
  count is the number of `hookDetails` entries sharing a `name::source` key.
  `recategorise_hook` must be applied first: a project-local hook reached through
  a tsconfig `baseUrl` arrives labelled "library" and becomes a custom-hook edge
  instead, so counting raw categories overstates this set.
* **Stage 4** `(:Custom_Hook)-[:USES_LIBRARY_HOOK]->(:Library_Hook)`, whose count
  comes from `custom_hook_internal.jinja2` directly. This path was already
  correct; it is included so a regression there cannot hide.

One project per run — Memgraph holds one project's graph at a time.

    uv run python scripts/verify_hook_counts.py --project SnapShot
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

GREEN, RED, RESET = "\033[32m", "\033[31m", "\033[0m"


def expected_edges(project: str) -> dict[tuple[str, str, str], int]:
    """(ownerName, hookName, hookSource) -> count, from the raw extraction JSON."""
    from src.config import get_settings
    from src.extraction.per_file_ingestion import is_custom_hook_name, recategorise_hook

    settings = get_settings()
    cfg = settings.projects.get(project)
    aliases = cfg.aliases if cfg else {}
    base_url = getattr(cfg, "base_url", "") if cfg else ""

    export_dir = REPO_ROOT / "graph_export" / project
    manifest = json.loads((export_dir / "file_manifest.json").read_text())
    file_paths = [f["filePath"] if isinstance(f, dict) else f for f in
                  (manifest["files"] if isinstance(manifest, dict) else manifest)]

    expected: dict[tuple[str, str, str], int] = {}

    # ── Stage 3: Function_Component -> Library_Hook ──
    for path in sorted((export_dir / "raw_extractions").glob("*.json")):
        results = json.loads(path.read_text())
        # Recover the repo-relative path the ingestion used; the filename is the
        # path with separators flattened to underscores.
        file_path = _unflatten(path.stem, file_paths)
        for comp in results.get("function_components", {}).get("components", []) or []:
            name = comp.get("name", "")
            if not name or is_custom_hook_name(name):
                continue  # routed to Custom_Hook; its hook edges come from Stage 4
            counts: Counter = Counter()
            first: dict[tuple[str, str], dict] = {}
            for hook in comp.get("hookDetails", []) or []:
                key = (hook["name"], hook.get("source", ""))
                counts[key] += 1
                first.setdefault(key, hook)
            for key, n in counts.items():
                hook = first[key]
                if file_path is None:
                    continue
                if recategorise_hook(hook, file_path, file_paths, aliases, base_url) != "library":
                    continue  # becomes a USES_CUSTOM_HOOK edge instead
                expected[(name, key[0], key[1])] = n

    # ── Stage 4: Custom_Hook -> Library_Hook ──
    cross_dir = export_dir / "raw_extractions_cross_file"
    if cross_dir.is_dir():
        for path in sorted(cross_dir.glob("*.json")):
            results = json.loads(path.read_text())
            for usage in (results.get("custom_hook_internal") or {}).get("customHookUsages", []):
                owner = usage.get("hookName") or usage.get("name")
                for lh in usage.get("libraryHooks") or []:
                    expected[(owner, lh["name"], lh.get("source", ""))] = lh.get("count", 1)

    return expected


def _unflatten(stem: str, file_paths: list[str]) -> str | None:
    """Map a flattened raw-extraction filename back to its repo-relative path."""
    for fp in file_paths:
        if fp.replace("/", "_").replace("\\", "_") == stem:
            return fp
    return None


def actual_edges() -> dict[tuple[str, str, str], int]:
    from src.graph.connection import run_query, close_driver

    try:
        rows = run_query(
            "MATCH (a)-[r:USES_LIBRARY_HOOK]->(lh) "
            "RETURN a.name AS owner, lh.name AS hook, lh.source AS source, r.count AS count"
        )
    finally:
        close_driver()
    return {(r["owner"], r["hook"], r["source"]): r["count"] for r in rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    args = parser.parse_args()

    expected = expected_edges(args.project)
    actual = actual_edges()

    missing = {k: v for k, v in expected.items() if k not in actual}
    extra = {k: v for k, v in actual.items() if k not in expected}
    wrong = {k: (expected[k], actual[k]) for k in expected.keys() & actual.keys()
             if expected[k] != actual[k]}

    print(f"edges expected: {len(expected)}   in graph: {len(actual)}")
    print(f"count distribution expected: {dict(sorted(Counter(expected.values()).items()))}")
    print(f"count distribution in graph: {dict(sorted(Counter(actual.values()).items()))}")

    for label, items in (("MISSING from graph", missing), ("EXTRA in graph", extra)):
        if items:
            print(f"\n{RED}{label}{RESET} ({len(items)}):")
            for k, v in sorted(items.items()):
                print(f"  {k[0]} -> {k[1]} ({k[2]}) = {v}")

    if wrong:
        print(f"\n{RED}COUNT MISMATCH{RESET} ({len(wrong)}):")
        for k, (e, a) in sorted(wrong.items()):
            print(f"  {k[0]} -> {k[1]} ({k[2]}): expected {e}, graph has {a}")

    if missing or extra or wrong:
        print(f"\n{RED}FAILED{RESET}")
        return 1

    multi = sum(1 for v in actual.values() if v > 1)
    print(f"\n{GREEN}All {len(actual)} edges match the raw extractions{RESET} "
          f"({multi} carry a count > 1)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
