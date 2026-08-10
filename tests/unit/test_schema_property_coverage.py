"""Every relationship property the schema documents must be written by a query.

Nothing connected the schema document to the Cypher implementing it, so an audit
prompted by the `USES_LIBRARY_HOOK.count` bug found two further properties
documented and never written at all: `USES_CUSTOM_HOOK.aliases`, and
`IMPORTS.specifiers` — the latter because the entire `IMPORTS` relationship is
unimplemented. This test is that connection.

**What this does not catch.** It would *not* have caught the count bug itself.
`MERGE_FC_USES_LIBRARY_HOOK` always contained `SET r.count = $count`; the defect
was one level up, in a caller passing the literal `1`. So this guard covers
"documented, and no query mentions it" — a real and demonstrated failure mode —
but not "written, with a constant". That class needs behavioural tests against
the ingestion functions; see `TestLibraryHookCallSiteCount` in
`test_custom_hook_ingestion.py`.

The check is deliberately weak (substring presence in `queries.py`) because a
stronger one would need to parse Cypher. Weak and honest beats strict and
brittle here — the point is that a *newly* documented property cannot be
forgotten entirely.

Known gaps are registered explicitly below rather than left invisible.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DOC = REPO_ROOT / "docs/phase_1/ReactJS_KG_Schema_details_v2.md"
QUERIES = REPO_ROOT / "src/graph/queries.py"

# Documented but not written by any query. Each entry is a real gap with a
# reason to stay open — not a way to silence the test.
KNOWN_GAPS = {
    # USES_CUSTOM_HOOK.aliases — "if imported under an alias". Needs extraction
    # support for `import { useKey as useHotkey }`, i.e. prompt work; no prompt
    # currently reports the local binding name.
    "aliases",
    # IMPORTS.specifiers — the entire (:File)-[:IMPORTS]->(:File) relationship is
    # unimplemented: no query in queries.py, 0 edges in every extracted graph.
    # The property cannot land before the relationship does.
    "specifiers",
}

# The "Common properties on all relationships" blockquote above §2.1
# (projectId, source_file_path, start_line, end_line, confidence) is out of
# scope: it is prefixed "include where available" and is aspirational rather
# than a per-relationship contract. Only source_file_path/start_line/end_line/
# confidence would be affected, and none of them is written today. Recorded here
# so the exclusion is a decision rather than a parsing accident.

_SECTION_2 = re.compile(r"^### 2\.\d")
_END_OF_SECTION_2 = re.compile(r"^## Node types")
_INLINE = re.compile(r"^\s*\*\s+Properties:\s*(.+)$")
_BARE = re.compile(r"^\s*\*\s+Properties:\s*$")
_SUB_BULLET = re.compile(r"^\s+\*\s+`([A-Za-z_][A-Za-z0-9_]*)`")
_BACKTICKED = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)`")


def documented_relationship_properties() -> set[str]:
    """Property names on `* Properties:` bullets within §2 of the schema doc."""
    lines = SCHEMA_DOC.read_text().splitlines()
    props: set[str] = set()
    in_section_2 = False
    collecting_sub_bullets = False

    for line in lines:
        if _SECTION_2.match(line):
            in_section_2 = True
        elif _END_OF_SECTION_2.match(line):
            in_section_2 = False
        if not in_section_2:
            continue

        if _BARE.match(line):
            # "* Properties:" followed by indented per-property bullets.
            collecting_sub_bullets = True
            continue

        inline = _INLINE.match(line)
        if inline:
            collecting_sub_bullets = False
            # Only the *first* backticked token is the property name. The rest of
            # the line is prose that also uses backticks — enum values
            # (`element` | `prop_value`), example literals, package names — and
            # collecting those made the guard demand queries for `production`
            # and `class_field`.
            name = _BACKTICKED.search(inline.group(1))
            if name:
                props.add(name.group(1))
            continue

        if collecting_sub_bullets:
            sub = _SUB_BULLET.match(line)
            if sub:
                props.add(sub.group(1))
            elif line.strip():
                collecting_sub_bullets = False

    return props


class TestSchemaPropertyCoverage:
    def test_the_parse_finds_properties(self):
        """The guard must not be able to pass by parsing nothing.

        This is the same failure mode as the pre-flight checkpoint guard, which
        scoped by a value that matched no rows and therefore always reported
        PASS. A guard whose input silently goes empty is worse than no guard.
        """
        props = documented_relationship_properties()
        assert len(props) >= 8, f"schema parse yielded only {props} — parser is broken"
        # Anchors that must always be present if the parse is working.
        assert {"count", "propName", "path"} <= props

    def test_every_documented_property_is_written_by_a_query(self):
        source = QUERIES.read_text()
        missing = {
            p for p in documented_relationship_properties()
            if p not in KNOWN_GAPS and p not in source
        }
        assert not missing, (
            f"Documented in the schema but never written to the graph: {sorted(missing)}. "
            "Either implement it in src/graph/queries.py or register it in KNOWN_GAPS "
            "with a reason."
        )

    @pytest.mark.parametrize("gap", sorted(KNOWN_GAPS))
    def test_known_gaps_are_still_gaps(self, gap):
        """Delist a gap once it is implemented, so the set stays honest."""
        assert gap not in QUERIES.read_text(), (
            f"'{gap}' is now written by a query — remove it from KNOWN_GAPS."
        )

    def test_known_gaps_are_actually_documented(self):
        """Guards against a stale exemption for a property the schema dropped."""
        props = documented_relationship_properties()
        stale = KNOWN_GAPS - props
        assert not stale, f"KNOWN_GAPS names properties the schema no longer documents: {stale}"

    def test_count_query_is_parameterised(self):
        """Necessary but not sufficient — see the module docstring.

        This held true throughout the period when every edge carried count=1,
        which is exactly why the behavioural tests exist as well.
        """
        assert "count" in documented_relationship_properties()
        assert "$count" in QUERIES.read_text()
