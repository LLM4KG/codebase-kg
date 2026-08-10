#!/usr/bin/env python3
"""Verify the Custom_Hook extraction fix against the live graph.

Checks the acceptance criteria from the plan, one project per run — Memgraph
holds exactly one project's graph at a time (Library nodes are keyed globally on
`name`, so a second project's dump aborts partway through on a shared dependency).

    uv run python scripts/verify_extraction_fix.py --project react-shopping-cart
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# Hook definitions present in each project's source, counted by hand from the repos.
EXPECTED = {
    "react-shopping-cart": {
        "custom_hooks": {
            "useCart", "useCartTotal", "useCartProducts", "useProducts",
            # Context accessor hooks defined inside the provider files. The WI
            # doc's hand count of 4 missed these; both are real definitions
            # (`const useCartContext = (): ICartContext => {...}`).
            "useCartContext", "useProductsContext",
        },
        "uses_component_must_be_positive": True,
    },
    "takenote": {
        "custom_hooks": {"useInterval", "useKey", "useBeforeUnload", "useTempState"},
        "uses_component_must_be_positive": True,
    },
    "SnapShot": {
        # The control: this project genuinely defines no custom hooks, so its zero
        # is correct and must stay zero. A non-zero count here means the new prompt
        # is inventing hooks.
        "custom_hooks": set(),
        "uses_component_must_be_positive": True,
    },
}

PASS, FAIL = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, choices=sorted(EXPECTED))
    args = parser.parse_args()

    from src.graph.connection import run_query, close_driver

    expected = EXPECTED[args.project]
    failures = 0

    def check(ok: bool, title: str, detail: str = "") -> None:
        nonlocal failures
        if not ok:
            failures += 1
        print(f"[{PASS if ok else FAIL}] {title}")
        for line in detail.splitlines():
            if line.strip():
                print(f"       {line}")

    try:
        # ── 1. Custom_Hook nodes exist, and are the right ones ──
        rows = run_query("MATCH (ch:Custom_Hook) RETURN ch.name AS name, ch.filePath AS path ORDER BY name")
        found = {r["name"] for r in rows}
        check(
            found == expected["custom_hooks"],
            f"Custom_Hook nodes: {len(found)} (expected {len(expected['custom_hooks'])})",
            f"found:    {sorted(found) or '—'}\n"
            f"expected: {sorted(expected['custom_hooks']) or '—'}\n"
            + ("\n".join(f"  {r['name']} -> {r['path']}" for r in rows)),
        )

        # ── 2. Hooks are actually wired to their consumers ──
        rows = run_query("MATCH ()-[r:USES_CUSTOM_HOOK]->() RETURN count(r) AS c")
        uses_hook = rows[0]["c"] if rows else 0
        check(
            uses_hook > 0 if expected["custom_hooks"] else uses_hook == 0,
            f"USES_CUSTOM_HOOK edges: {uses_hook}",
            "A Custom_Hook node nothing points at is only half the fix.",
        )

        # ── 3. Composition edges — the adjacent finding ──
        rows = run_query("MATCH ()-[r:USES_COMPONENT]->() RETURN count(r) AS c")
        uses_component = rows[0]["c"] if rows else 0
        check(
            uses_component > 0,
            f"USES_COMPONENT edges: {uses_component}",
            "Was 0 for react-shopping-cart before the baseUrl resolver.",
        )

        # ── 4. No orphan Library_Hooks pointing at project-local paths ──
        hooks = run_query("MATCH (lh:Library_Hook) RETURN lh.name AS name, lh.source AS source ORDER BY name")
        libs = {r["name"] for r in run_query("MATCH (l:Library) RETURN l.name AS name")}
        orphans = [(r["name"], r["source"]) for r in hooks if r["source"] not in libs]
        # A source containing '/' that is not a scoped package is a path, not a package.
        path_shaped = [
            (n, s) for n, s in orphans
            if s and not s.startswith("@") and ("/" in s or s in {"models", "utils", "services"})
        ]
        check(
            not path_shaped,
            f"Orphan Library_Hooks with path-shaped source: {len(path_shaped)}",
            "\n".join(f"  {n} -> {s}" for n, s in path_shaped)
            + (f"\n(other orphans, likely legitimate: {orphans})" if orphans and not path_shaped else ""),
        )

        # ── 5. Hook state edges (pre-existing routing, works once nodes exist) ──
        rows = run_query(
            "MATCH (ch:Custom_Hook)-[r:DECLARES_STATE]->(sv:State_Variable) "
            "RETURN ch.name AS hook, sv.name AS state ORDER BY hook, state"
        )
        print(f"[info] Custom_Hook DECLARES_STATE edges: {len(rows)}"
              + (f" — {[(r['hook'], r['state']) for r in rows]}" if rows else ""))

        # ── 6. bug_fix.cypher returns a non-empty result for a hook anchor ──
        if args.project == "react-shopping-cart":
            template = (REPO_ROOT / "src/retrieval/templates/bug_fix.cypher").read_text()
            proj = run_query("MATCH (p:Project) RETURN p.projectId AS id")[0]["id"]
            rows = run_query(template, {"projectId": proj, "anchorNames": ["useCartProducts"]})
            real_path = "src/contexts/cart-context/useCartProducts.ts"
            check(
                bool(rows) and rows[0]["filePath"] == real_path,
                f"bug_fix.cypher on anchor 'useCartProducts': {len(rows)} row(s)",
                (f"filePath: {rows[0]['filePath']}\n"
                 f"type:     {rows[0]['componentType']}\n"
                 f"usedBy:   {[c for c in rows[0]['usedByComponents'] if c.get('name')]}"
                 if rows else
                 "Zero rows — this is the gate criterion that has never passed."),
            )
    finally:
        try:
            close_driver()
        except Exception:
            pass

    print()
    print(f"\033[32mAll checks passed\033[0m" if not failures
          else f"\033[31m{failures} check(s) failed\033[0m")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
