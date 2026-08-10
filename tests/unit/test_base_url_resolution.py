"""Tests for project-local import resolution via tsconfig `baseUrl`.

The pilot's react-shopping-cart KG had zero Custom_Hook nodes and zero
USES_COMPONENT edges. Root cause: that project sets `"baseUrl": "src"` and imports
with bare specifiers (`from 'contexts/cart-context'`), which every resolver treated
as an external npm package. These tests pin the relative → alias → baseUrl ladder
and, critically, that real packages still fall through.
"""

import pytest

from src.extraction.cross_file import (
    resolve_base_url,
    resolve_import_path,
    resolve_to_manifest_file,
)

# Mirrors react-shopping-cart's actual layout.
CART_MANIFEST = [
    "src/contexts/cart-context/index.ts",
    "src/contexts/cart-context/useCartProducts.ts",
    "src/components/Cart/Cart.tsx",
    "src/components/Cart/CartProducts.tsx",
    "src/models/index.ts",
    "src/utils/formatPrice.ts",
]
CART_FILE = "src/components/Cart/Cart.tsx"


class TestResolveBaseUrl:
    def test_bare_specifier_resolves_under_base_url(self):
        assert resolve_base_url("contexts/cart-context", "src") == "src/contexts/cart-context"

    def test_single_segment_specifier(self):
        assert resolve_base_url("models", "src") == "src/models"

    def test_no_base_url_configured_returns_none(self):
        # takenote uses aliases only; it must be unaffected.
        assert resolve_base_url("contexts/cart-context", "") is None

    def test_relative_imports_are_not_base_url_resolved(self):
        assert resolve_base_url("./CartProducts", "src") is None
        assert resolve_base_url("../models", "src") is None

    def test_scoped_and_absolute_packages_excluded(self):
        assert resolve_base_url("@mui/material", "src") is None
        assert resolve_base_url("/etc/passwd", "src") is None

    def test_empty_source(self):
        assert resolve_base_url("", "src") is None


class TestResolveImportPathLadder:
    def test_relative_wins_first(self):
        assert (
            resolve_import_path("./CartProducts", CART_FILE, {}, "src")
            == "src/components/Cart/CartProducts"
        )

    def test_alias_beats_base_url(self):
        # An alias-prefixed source must not be re-rooted under base_url.
        aliases = {"@": "src/client"}
        assert (
            resolve_import_path("@/components/NoteList", "src/client/App.tsx", aliases, "src")
            == "src/client/components/NoteList"
        )

    def test_base_url_is_the_last_resort(self):
        assert (
            resolve_import_path("contexts/cart-context", CART_FILE, {}, "src")
            == "src/contexts/cart-context"
        )

    def test_without_base_url_bare_specifier_is_unresolvable(self):
        # The pre-fix behaviour, pinned so a regression is visible.
        assert resolve_import_path("contexts/cart-context", CART_FILE, {}, "") is None

    def test_empty_source_returns_none(self):
        assert resolve_import_path("", CART_FILE, {}, "src") is None


class TestResolveToManifestFile:
    def test_bare_specifier_resolves_to_index_file(self):
        assert (
            resolve_to_manifest_file("contexts/cart-context", CART_FILE, CART_MANIFEST, {}, "src")
            == "src/contexts/cart-context/index.ts"
        )

    def test_bare_specifier_resolves_to_direct_file(self):
        assert (
            resolve_to_manifest_file(
                "contexts/cart-context/useCartProducts", CART_FILE, CART_MANIFEST, {}, "src"
            )
            == "src/contexts/cart-context/useCartProducts.ts"
        )

    def test_relative_sibling_resolves(self):
        assert (
            resolve_to_manifest_file("./CartProducts", CART_FILE, CART_MANIFEST, {}, "src")
            == "src/components/Cart/CartProducts.tsx"
        )

    @pytest.mark.parametrize("package", ["react", "styled-components", "@mui/material"])
    def test_npm_packages_do_not_resolve(self, package):
        """The manifest lookup is the arbiter.

        `react` does produce a candidate path `src/react` under base_url, but no
        such file exists, so it correctly resolves to None. This is what keeps
        real dependencies from being mistaken for project-local modules.
        """
        assert resolve_to_manifest_file(package, CART_FILE, CART_MANIFEST, {}, "src") is None

    def test_unknown_project_local_path_returns_none(self):
        assert (
            resolve_to_manifest_file("contexts/does-not-exist", CART_FILE, CART_MANIFEST, {}, "src")
            is None
        )


# react-shopping-cart uses a directory-per-component layout with a barrel in every
# directory: `src/components/Loader/index.ts` does `export { default } from './Loader'`.
# Imports therefore land on the barrel while the node lives in the implementation
# file — a second indirection behind baseUrl, and the reason USES_COMPONENT stayed
# at 0 even for *relative* imports.
BARREL_MANIFEST = [
    "src/components/Loader/index.ts",
    "src/components/Loader/Loader.tsx",
    "src/components/Cart/Cart.tsx",
    "src/components/Cart/CartProducts/index.ts",
    "src/components/Cart/CartProducts/CartProducts.tsx",
    "src/contexts/cart-context/index.ts",
    "src/contexts/cart-context/useCart.ts",
]


class TestBarrelResolution:
    def test_hook_import_resolves_past_the_barrel(self):
        """`import { useCart } from 'contexts/cart-context'` must reach useCart.ts."""
        assert (
            resolve_to_manifest_file(
                "contexts/cart-context", "src/components/Cart/Cart.tsx",
                BARREL_MANIFEST, {}, "src", symbol_name="useCart",
            )
            == "src/contexts/cart-context/useCart.ts"
        )

    def test_relative_component_import_resolves_past_the_barrel(self):
        assert (
            resolve_to_manifest_file(
                "./CartProducts", "src/components/Cart/Cart.tsx",
                BARREL_MANIFEST, {}, "src", symbol_name="CartProducts",
            )
            == "src/components/Cart/CartProducts/CartProducts.tsx"
        )

    def test_without_symbol_name_it_still_lands_on_the_barrel(self):
        """The pre-fix outcome, pinned: a uid pointing at index.ts matches no node."""
        assert (
            resolve_to_manifest_file(
                "contexts/cart-context", "src/components/Cart/Cart.tsx",
                BARREL_MANIFEST, {}, "src",
            )
            == "src/contexts/cart-context/index.ts"
        )

    def test_symbol_name_does_not_break_barrel_less_directories(self):
        """App.tsx's real import: `from 'components/Cart'`, a directory with no barrel.

        The symbol-named file is found directly, which is the same answer the
        extension expansion would have reached — the new leg must not change it.
        """
        assert (
            resolve_to_manifest_file(
                "components/Cart", "src/components/App/App.tsx",
                BARREL_MANIFEST, {}, "src", symbol_name="Cart",
            )
            == "src/components/Cart/Cart.tsx"
        )

    def test_unknown_symbol_falls_back_to_the_barrel(self):
        assert (
            resolve_to_manifest_file(
                "contexts/cart-context", "src/components/Cart/Cart.tsx",
                BARREL_MANIFEST, {}, "src", symbol_name="useNotAThing",
            )
            == "src/contexts/cart-context/index.ts"
        )
