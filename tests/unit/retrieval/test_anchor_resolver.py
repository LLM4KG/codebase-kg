"""Tests for the anchor resolver (WP8) — a pure function over candidate rows, no database."""

from __future__ import annotations

from src.retrieval.anchor_resolver import (
    FUZZY_CUTOFF,
    known_routes,
    resolve_anchors,
    resolved_names,
    spec_path_hints,
)

ROWS = [
    {"name": "CartProduct", "uid": "CartProduct::src/components/Cart/CartProduct.tsx",
     "filePath": "src/components/Cart/CartProduct.tsx", "label": "Function_Component"},
    {"name": "CartProducts", "uid": "CartProducts::src/components/Cart/CartProducts.tsx",
     "filePath": "src/components/Cart/CartProducts.tsx", "label": "Function_Component"},
    {"name": "useCart", "uid": "useCart::src/contexts/cart-context/useCart.ts",
     "filePath": "src/contexts/cart-context/useCart.ts", "label": "Custom_Hook"},
    # The cypher_templates.md L4 case: one name, two files.
    {"name": "Button", "uid": "Button::src/components/Button.tsx",
     "filePath": "src/components/Button.tsx", "label": "Function_Component"},
    {"name": "Button", "uid": "Button::src/ui/Button.tsx",
     "filePath": "src/ui/Button.tsx", "label": "Function_Component"},
]


def only(names, spec=""):
    return resolve_anchors(names, ROWS, spec)[0]


def test_exact_match():
    r = only(["CartProduct"])
    assert (r.status, r.matched_by) == ("exact", "exact")
    assert r.name == "CartProduct"
    assert r.uid == "CartProduct::src/components/Cart/CartProduct.tsx"
    assert r.alternatives == ()


def test_case_insensitive_match():
    r = only(["cartproduct"])
    assert (r.status, r.matched_by) == ("case_insensitive", "case_insensitive")
    assert r.name == "CartProduct"


def test_fuzzy_match_on_a_transposition():
    r = only(["CartPorduct"])
    assert (r.status, r.matched_by) == ("fuzzy", "fuzzy")
    assert r.name == "CartProduct"
    assert r.score is not None and r.score >= FUZZY_CUTOFF


def test_exact_wins_over_fuzzy_for_a_real_sibling():
    # "CartProducts" is 0.957 similar to "CartProduct", so only running exact first
    # keeps the plural from being rewritten to the singular.
    r = only(["CartProducts"])
    assert r.status == "exact"
    assert r.name == "CartProducts"


def test_unresolved_when_nothing_is_close():
    r = only(["ShoppingBasketWidget"])
    assert (r.status, r.matched_by) == ("unresolved", "none")
    assert r.name is None and r.uid is None
    assert not r.resolved


def test_ambiguous_keeps_every_candidate():
    r = only(["Button"])
    assert r.status == "ambiguous"
    assert r.matched_by == "exact"
    assert len(r.alternatives) == 1
    assert r.uid not in r.alternatives


def test_ambiguity_prefers_the_path_the_spec_names():
    r = only(["Button"], spec="Restyle the Button in src/ui/Button.tsx to use the new token.")
    assert r.status == "ambiguous"
    assert r.file_path == "src/ui/Button.tsx"
    assert r.alternatives == ("Button::src/components/Button.tsx",)


def test_ambiguity_without_a_path_hint_is_still_deterministic():
    first = only(["Button"])
    second = resolve_anchors(["Button"], list(reversed(ROWS)), "")[0]
    assert first.uid == second.uid


def test_spec_path_hints_picks_up_paths_and_bare_filenames():
    hints = spec_path_hints("Fix `src/contexts/cart-context/useCart.ts` and CartProduct.tsx.")
    assert "cart-context" in hints
    assert "useCart" in hints
    assert "CartProduct" in hints


def test_resolved_names_dedupes_and_keeps_order():
    resolutions = resolve_anchors(["cartproduct", "CartProduct", "useCart", "Nope"], ROWS)
    assert resolved_names(resolutions) == ["CartProduct", "useCart"]


def test_resolutions_line_up_with_the_requested_names():
    names = ["CartProduct", "Nope", "useCart"]
    resolutions = resolve_anchors(names, ROWS)
    assert [r.requested for r in resolutions] == names


def test_as_dict_is_json_safe():
    d = only(["Button"]).as_dict()
    assert isinstance(d["alternatives"], list)
    assert set(d) == {"requested", "status", "matched_by", "name", "uid",
                      "file_path", "score", "alternatives"}


def test_known_routes_splits_present_from_absent():
    present, absent = known_routes(["/", "/notes/trash"], ["/", "/app"])
    assert present == ["/"]
    assert absent == ["/notes/trash"]


def test_empty_names_resolve_to_nothing():
    assert resolve_anchors([], ROWS) == []
    assert resolved_names([]) == []
