"""Resolve classifier anchor names against the nodes a project's graph actually holds.

The three anchor-scoped Cypher templates bind their anchor with a non-optional
`WHERE anchor.name IN $anchorNames`. That predicate is exact and case-sensitive, so a
name the classifier got slightly wrong — or a name that does not exist at all — matches
nothing, the query returns zero rows, and the KG-augmented condition silently renders an
empty context (see `cypher_templates.md` §2 and WP8).

This module turns the raw names into an explicit, reportable resolution before dispatch:

    rows          `anchor_candidates.cypher` — every Function_Component / Class_Component /
                  Custom_Hook in the project, as {name, uid, filePath, label}.
    resolve_anchors(names, rows, spec) -> list[AnchorResolution]

It is a pure function over those rows: no database, no I/O, unit-testable on a literal
list. `KGAugmentedRetriever` calls it only under `anchor_resolution = "hardened"`; the
default `"strict"` path never imports it, so no published result moves.

The ladder is deliberately shallow — exact, then case-insensitive, then a `difflib`
near-miss above FUZZY_CUTOFF. It cannot detect a *plausible but wrong* anchor: a name
that resolves cleanly to the wrong component is indistinguishable here from a correct
one, and the WP8 note states that limit rather than papering over it.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

# Minimum difflib.SequenceMatcher ratio for a near-miss to count as the same entity.
# 0.80 admits a realistic typo ("CartProdcut" -> "CartProduct", ratio 0.909) and rejects
# an unrelated name ("Foo" -> "CartProduct", 0.143). It does NOT separate a typo from a
# genuinely different sibling ("CartProduct" -> "CartProducts" is 0.957), which is why
# fuzzy matching runs only after exact and case-insensitive matching have both failed:
# when both names exist in the graph, the exact rung has already claimed the right one.
FUZZY_CUTOFF = 0.80

# Statuses, in the order the ladder produces them. `ambiguous` is not a rung: it is
# what any rung reports when it ends up with more than one candidate.
STATUSES = ("exact", "case_insensitive", "fuzzy", "ambiguous", "unresolved")

_PATH_TOKEN = re.compile(r"[\w./-]*[\w-]+\.(?:tsx?|jsx?)|[\w-]+/[\w./-]+")


@dataclass(frozen=True)
class AnchorResolution:
    """What one classifier anchor name resolved to, and how."""

    requested: str
    status: str
    matched_by: str          # exact | case_insensitive | fuzzy | none — the rung that fired
    name: str | None = None  # the graph node's name, to pass in $anchorNames
    uid: str | None = None
    file_path: str | None = None
    score: float | None = None                        # difflib ratio, fuzzy only
    alternatives: tuple[str, ...] = field(default_factory=tuple)  # other candidates' uids

    @property
    def resolved(self) -> bool:
        return self.name is not None

    def as_dict(self) -> dict:
        """A JSON-safe record for `RetrievalResult.metadata`."""
        return {
            "requested": self.requested,
            "status": self.status,
            "matched_by": self.matched_by,
            "name": self.name,
            "uid": self.uid,
            "file_path": self.file_path,
            "score": self.score,
            "alternatives": list(self.alternatives),
        }


def spec_path_hints(spec: str) -> set[str]:
    """Path segments named anywhere in the task statement.

    Used only to order the candidates of an ambiguous name — the `Button` in
    `components/` versus the `Button` in `ui/` case of `cypher_templates.md` L4. A
    statement that names no path yields an empty set and the ordering falls back to uid,
    so the choice stays deterministic either way.
    """
    hints: set[str] = set()
    for token in _PATH_TOKEN.findall(spec or ""):
        for part in token.replace("\\", "/").split("/"):
            part = part.strip(".,;:`'\"()[]")
            if part:
                hints.add(part)
                hints.add(part.rsplit(".", 1)[0])
    return {h for h in hints if h}


def _path_overlap(file_path: str, hints: set[str]) -> int:
    if not hints or not file_path:
        return 0
    parts = {p for p in file_path.split("/") if p}
    parts |= {p.rsplit(".", 1)[0] for p in parts}
    return len(parts & hints)


def _rank(candidates: list[dict], hints: set[str]) -> list[dict]:
    """Best candidate first: most path segments shared with the spec, then uid."""
    return sorted(
        candidates,
        key=lambda c: (-_path_overlap(c.get("filePath") or "", hints), c.get("uid") or ""),
    )


def _resolve_one(name: str, rows: list[dict], hints: set[str]) -> AnchorResolution:
    exact = [r for r in rows if r.get("name") == name]
    if exact:
        return _build(name, _rank(exact, hints), "exact")

    folded = [r for r in rows if (r.get("name") or "").lower() == name.lower()]
    if folded:
        return _build(name, _rank(folded, hints), "case_insensitive")

    graph_names = sorted({r.get("name") or "" for r in rows if r.get("name")})
    near = difflib.get_close_matches(name, graph_names, n=3, cutoff=FUZZY_CUTOFF)
    if near:
        best = near[0]
        score = difflib.SequenceMatcher(None, name, best).ratio()
        hits = _rank([r for r in rows if r.get("name") == best], hints)
        return _build(name, hits, "fuzzy", score=round(score, 3))

    return AnchorResolution(requested=name, status="unresolved", matched_by="none")


def _build(name: str, ranked: list[dict], matched_by: str, score: float | None = None) -> AnchorResolution:
    chosen = ranked[0]
    return AnchorResolution(
        requested=name,
        status="ambiguous" if len(ranked) > 1 else matched_by,
        matched_by=matched_by,
        name=chosen.get("name"),
        uid=chosen.get("uid"),
        file_path=chosen.get("filePath"),
        score=score,
        alternatives=tuple(r.get("uid") or "" for r in ranked[1:]),
    )


def resolve_anchors(
    names: list[str], rows: list[dict], spec: str = ""
) -> list[AnchorResolution]:
    """Resolve each requested anchor name against the project's anchor-eligible nodes.

    `rows` come from `anchor_candidates.cypher`. Order and duplicates of `names` are
    preserved as the classifier produced them, so the result lines up one-to-one with
    `ClassifierResult.anchor_names` in the retrieval metadata.
    """
    hints = spec_path_hints(spec)
    return [_resolve_one(n, rows, hints) for n in names]


def resolved_names(resolutions: list[AnchorResolution]) -> list[str]:
    """The graph node names to bind to `$anchorNames`, de-duplicated, order preserved."""
    out: list[str] = []
    for r in resolutions:
        if r.name and r.name not in out:
            out.append(r.name)
    return out


def known_routes(routes: list[str], graph_routes: list[str]) -> tuple[list[str], list[str]]:
    """Split requested routes into (present in the graph, absent from it).

    `feature_addition_b` already warns about an absent route in the assembled context;
    this reports the same split in the metadata so it is machine-readable.
    """
    known = set(graph_routes)
    return [r for r in routes if r in known], [r for r in routes if r not in known]
