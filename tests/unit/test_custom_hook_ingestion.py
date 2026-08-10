"""Tests for Custom_Hook node creation and hook re-categorisation.

Custom_Hook nodes were absent from every extracted project: no Stage 2 prompt
targeted hook *definitions*, and project-local hooks imported via tsconfig
`baseUrl` were categorised "library", producing orphan Library_Hook nodes.
"""

from unittest.mock import patch

import pytest

from src.extraction.per_file_ingestion import (
    _ingest_custom_hooks,
    _ingest_function_components,
    recategorise_hook,
)

CART_MANIFEST = [
    "src/contexts/cart-context/index.ts",
    "src/contexts/cart-context/useCartProducts.ts",
    "src/components/Cart/Cart.tsx",
]
CART_FILE = "src/components/Cart/Cart.tsx"


class TestIngestCustomHooks:
    def test_creates_node_per_definition(self):
        results = {
            "custom_hooks": {
                "customHooks": [
                    {"name": "useCartProducts", "syntax": "arrow", "exportType": "default"},
                    {"name": "useCartTotal", "syntax": "arrow", "exportType": "named"},
                ]
            }
        }
        with patch("src.graph.ingestion.ingest_custom_hook_as_node") as mock:
            _ingest_custom_hooks("src/contexts/cart-context/useCartProducts.ts", results)

        assert mock.call_count == 2
        assert [c.args[0]["name"] for c in mock.call_args_list] == [
            "useCartProducts",
            "useCartTotal",
        ]

    def test_missing_key_is_a_no_op(self):
        """Graphs extracted before this prompt existed must still ingest."""
        with patch("src.graph.ingestion.ingest_custom_hook_as_node") as mock:
            _ingest_custom_hooks(CART_FILE, {"function_components": {"components": []}})
        mock.assert_not_called()

    def test_empty_list_is_a_no_op(self):
        with patch("src.graph.ingestion.ingest_custom_hook_as_node") as mock:
            _ingest_custom_hooks(CART_FILE, {"custom_hooks": {"customHooks": []}})
        mock.assert_not_called()

    def test_non_hook_name_is_rejected(self):
        """A component must never enter the graph as a Custom_Hook."""
        results = {
            "custom_hooks": {
                "customHooks": [
                    {"name": "CartProducts", "syntax": "arrow", "exportType": "default"},
                    {"name": "useCart", "syntax": "arrow", "exportType": "named"},
                ]
            }
        }
        with patch("src.graph.ingestion.ingest_custom_hook_as_node") as mock:
            _ingest_custom_hooks(CART_FILE, results)

        assert mock.call_count == 1
        assert mock.call_args_list[0].args[0]["name"] == "useCart"

    def test_unnamed_entry_skipped(self):
        results = {"custom_hooks": {"customHooks": [{"name": "", "syntax": "arrow"}]}}
        with patch("src.graph.ingestion.ingest_custom_hook_as_node") as mock:
            _ingest_custom_hooks(CART_FILE, results)
        mock.assert_not_called()


class TestRecategoriseHook:
    def test_base_url_hook_becomes_custom(self):
        """The react-shopping-cart case: `import { useCart } from 'contexts/cart-context'`."""
        hook = {"name": "useCart", "category": "library", "source": "contexts/cart-context"}
        assert recategorise_hook(hook, CART_FILE, CART_MANIFEST, {}, "src") == "custom"

    def test_real_package_stays_library(self):
        hook = {"name": "useState", "category": "library", "source": "react"}
        assert recategorise_hook(hook, CART_FILE, CART_MANIFEST, {}, "src") == "library"

    def test_alias_hook_becomes_custom(self):
        hook = {"name": "useKey", "category": "library", "source": "@/utils/hooks"}
        manifest = ["src/client/utils/hooks.ts"]
        assert (
            recategorise_hook(hook, "src/client/App.tsx", manifest, {"@": "src/client"}, "")
            == "custom"
        )

    def test_already_custom_is_untouched(self):
        hook = {"name": "useCart", "category": "custom", "source": "./useCart"}
        assert recategorise_hook(hook, CART_FILE, CART_MANIFEST, {}, "src") == "custom"

    def test_local_source_is_untouched(self):
        hook = {"name": "useThing", "category": "library", "source": "local"}
        assert recategorise_hook(hook, CART_FILE, CART_MANIFEST, {}, "src") == "library"

    def test_without_base_url_nothing_is_recategorised(self):
        """Pins the pre-fix behaviour so the regression stays visible."""
        hook = {"name": "useCart", "category": "library", "source": "contexts/cart-context"}
        assert recategorise_hook(hook, CART_FILE, CART_MANIFEST, {}, "") == "library"


def _cart_results(hook_details):
    return {
        "function_components": {
            "components": [{
                "name": "Cart",
                "syntax": "arrow",
                "usesHooks": True,
                "exportType": "default",
                "hookDetails": hook_details,
            }]
        }
    }


class TestFunctionComponentHookRouting:
    """Stage 3 creates Library_Hook edges only.

    Component→Custom_Hook edges are deferred to Stage 4: MERGE_FC_USES_CUSTOM_HOOK
    matches both endpoints, and per-file ingestion runs in path order, so
    src/components/Cart/Cart.tsx is processed before
    src/contexts/cart-context/useCart.ts exists as a node.
    """

    def test_library_hooks_are_ingested_in_stage_3(self):
        results = _cart_results([
            {"name": "useState", "category": "library", "source": "react"},
            {"name": "useCart", "category": "library", "source": "contexts/cart-context"},
        ])
        with patch("src.graph.ingestion.ingest_function_component"), \
             patch("src.graph.ingestion.ingest_library_hook") as lib, \
             patch("src.graph.ingestion.ingest_custom_hook_usage") as custom:
            _ingest_function_components(
                CART_FILE, results, CART_MANIFEST, aliases={}, base_url="src"
            )

        assert [c.args[0]["name"] for c in lib.call_args_list] == ["useState"]
        custom.assert_not_called()  # deferred, not dropped


class TestLibraryHookCallSiteCount:
    """`USES_LIBRARY_HOOK.count` is "call-site occurrences within the component"
    (schema §2.4) but was hardcoded to 1 on every Stage 3 edge — 16 of 59 edges
    across the three extracted projects were understated, by up to 4x.

    `hookDetails` carries one entry per call site, so the tally was always
    available; `_ingest_function_components` computed it and discarded it.
    """

    def _counts(self, hook_details):
        results = _cart_results(hook_details)
        with patch("src.graph.ingestion.ingest_function_component"), \
             patch("src.graph.ingestion.ingest_library_hook") as lib, \
             patch("src.graph.ingestion.ingest_custom_hook_usage"):
            _ingest_function_components(
                CART_FILE, results, CART_MANIFEST, aliases={}, base_url="src"
            )
        # (name, count) per emitted edge; count is the 3rd positional arg.
        return [(c.args[0]["name"], c.args[2]) for c in lib.call_args_list]

    def test_repeated_hook_yields_one_edge_carrying_the_count(self):
        assert self._counts([
            {"name": "useState", "category": "library", "source": "react"},
            {"name": "useState", "category": "library", "source": "react"},
            {"name": "useState", "category": "library", "source": "react"},
        ]) == [("useState", 3)]

    def test_single_call_site_still_counts_one(self):
        assert self._counts([
            {"name": "useEffect", "category": "library", "source": "react"},
        ]) == [("useEffect", 1)]

    def test_counts_are_per_hook_not_per_component(self):
        assert self._counts([
            {"name": "useSelector", "category": "library", "source": "react-redux"},
            {"name": "useState", "category": "library", "source": "react"},
            {"name": "useSelector", "category": "library", "source": "react-redux"},
            {"name": "useSelector", "category": "library", "source": "react-redux"},
        ]) == [("useSelector", 3), ("useState", 1)]

    def test_same_name_from_different_packages_stays_two_edges(self):
        """The key is name::source — two distinct Library_Hook nodes."""
        assert self._counts([
            {"name": "useForm", "category": "library", "source": "react-hook-form"},
            {"name": "useForm", "category": "library", "source": "@mantine/form"},
            {"name": "useForm", "category": "library", "source": "react-hook-form"},
        ]) == [("useForm", 2), ("useForm", 1)]

    def test_source_order_is_preserved(self):
        """Dict insertion order replaced the seen_hooks set; first occurrence wins."""
        assert [n for n, _c in self._counts([
            {"name": "useRef", "category": "library", "source": "react"},
            {"name": "useMemo", "category": "library", "source": "react"},
            {"name": "useRef", "category": "library", "source": "react"},
        ])] == ["useRef", "useMemo"]

    def test_recategorised_hooks_are_counted_but_not_emitted_here(self):
        """`recategorise_hook` reclassifies a baseUrl import to "custom" *after*
        counting. The count is keyed on name::source and only read on the library
        branch, so the repeated custom hook must simply not appear."""
        assert self._counts([
            {"name": "useState", "category": "library", "source": "react"},
            {"name": "useCart", "category": "library", "source": "contexts/cart-context"},
            {"name": "useCart", "category": "library", "source": "contexts/cart-context"},
        ]) == [("useState", 1)]

    def test_no_hooks_emits_nothing(self):
        assert self._counts([]) == []


class TestDeferredCustomHookUsage:
    def test_base_url_hook_produces_a_usage_edge(self):
        """End-to-end: a baseUrl hook must produce USES_CUSTOM_HOOK, not a Library_Hook."""
        from src.extraction.cross_file import _ingest_component_custom_hook_usage

        all_results = {CART_FILE: _cart_results([
            {"name": "useState", "category": "library", "source": "react"},
            {"name": "useCart", "category": "library", "source": "contexts/cart-context"},
        ])}
        with patch("src.graph.ingestion.ingest_custom_hook_usage") as custom:
            _ingest_component_custom_hook_usage(
                all_results, CART_MANIFEST, aliases={}, base_url="src"
            )

        assert [c.args[0]["name"] for c in custom.call_args_list] == ["useCart"]

    def test_without_base_url_nothing_is_deferred(self):
        """The pre-fix outcome: useCart stayed an orphan Library_Hook."""
        from src.extraction.cross_file import _ingest_component_custom_hook_usage

        all_results = {CART_FILE: _cart_results([
            {"name": "useCart", "category": "library", "source": "contexts/cart-context"},
        ])}
        with patch("src.graph.ingestion.ingest_custom_hook_usage") as custom:
            _ingest_component_custom_hook_usage(all_results, CART_MANIFEST, aliases={}, base_url="")

        custom.assert_not_called()

    def test_hook_definitions_are_skipped(self):
        """A useXxx entry is a Custom_Hook node; hook→hook edges come from Stage 4's own prompt."""
        from src.extraction.cross_file import _ingest_component_custom_hook_usage

        all_results = {
            "src/contexts/cart-context/useCart.ts": {
                "function_components": {"components": [{
                    "name": "useCart",
                    "hookDetails": [
                        {"name": "useCartContext", "category": "library",
                         "source": "contexts/cart-context"},
                    ],
                }]}
            }
        }
        with patch("src.graph.ingestion.ingest_custom_hook_usage") as custom:
            _ingest_component_custom_hook_usage(
                all_results, CART_MANIFEST, aliases={}, base_url="src"
            )

        custom.assert_not_called()

    def test_duplicate_hook_uses_produce_one_edge(self):
        from src.extraction.cross_file import _ingest_component_custom_hook_usage

        all_results = {CART_FILE: _cart_results([
            {"name": "useCart", "category": "library", "source": "contexts/cart-context"},
            {"name": "useCart", "category": "library", "source": "contexts/cart-context"},
        ])}
        with patch("src.graph.ingestion.ingest_custom_hook_usage") as custom:
            _ingest_component_custom_hook_usage(
                all_results, CART_MANIFEST, aliases={}, base_url="src"
            )

        assert custom.call_count == 1


class TestFindComponentUnderDirectory:
    """Barrel resolution for components matches on the NODE's name, not the filename.

    This is what makes a renaming re-export work:
    `export { CartProvider } from './CartContextProvider'` — no file is named
    CartProvider, so filename matching would fail.
    """

    INDEX = {
        "Loader::src/components/Loader/Loader.tsx": {
            "name": "Loader", "filePath": "src/components/Loader/Loader.tsx", "uid": "x",
        },
        "CartProvider::src/contexts/cart-context/CartContextProvider.tsx": {
            "name": "CartProvider",
            "filePath": "src/contexts/cart-context/CartContextProvider.tsx",
            "uid": "y",
        },
        "CartProduct::src/components/Cart/CartProducts/CartProduct/CartProduct.tsx": {
            "name": "CartProduct",
            "filePath": "src/components/Cart/CartProducts/CartProduct/CartProduct.tsx",
            "uid": "z",
        },
    }

    def test_finds_component_beside_the_barrel(self):
        from src.extraction.cross_file import _find_component_under_directory
        found = _find_component_under_directory("Loader", "src/components/Loader", self.INDEX)
        assert found["filePath"] == "src/components/Loader/Loader.tsx"

    def test_resolves_a_renaming_re_export(self):
        from src.extraction.cross_file import _find_component_under_directory
        found = _find_component_under_directory(
            "CartProvider", "src/contexts/cart-context", self.INDEX
        )
        assert found["filePath"] == "src/contexts/cart-context/CartContextProvider.tsx"

    def test_does_not_claim_nested_components(self):
        """A barrel must not reach into a sub-directory's own component."""
        from src.extraction.cross_file import _find_component_under_directory
        assert _find_component_under_directory(
            "CartProduct", "src/components/Cart/CartProducts", self.INDEX
        ) is None

    def test_unknown_name_returns_none(self):
        from src.extraction.cross_file import _find_component_under_directory
        assert _find_component_under_directory("Nope", "src/components/Loader", self.INDEX) is None


class TestStage4FileGating:
    """Hook-only files must reach Stage 4.

    The predicate's docstring always said "hooks", but no key carried them, so a
    file defining only hooks looked empty and was skipped — which meant
    custom_hook_internal.jinja2 never ran on a hook file and hook→hook edges
    (useCart → useCartProducts) could not exist.
    """

    def test_hook_only_file_is_included(self):
        from src.extraction.cross_file import _file_has_cross_file_content
        results = {
            "function_components": {"components": []},
            "class_components": {"classComponents": []},
            "contexts": {"contexts": []},
            "custom_hooks": {"customHooks": [{"name": "useCart"}]},
        }
        assert _file_has_cross_file_content(results) is True

    def test_pre_fix_shape_would_have_been_skipped(self):
        from src.extraction.cross_file import _file_has_cross_file_content
        results = {
            "function_components": {"components": []},
            "class_components": {"classComponents": []},
            "contexts": {"contexts": []},
        }
        assert _file_has_cross_file_content(results) is False

    def test_component_file_still_included(self):
        from src.extraction.cross_file import _file_has_cross_file_content
        assert _file_has_cross_file_content(
            {"function_components": {"components": [{"name": "Cart"}]}}
        ) is True

    def test_truly_empty_file_still_skipped(self):
        from src.extraction.cross_file import _file_has_cross_file_content
        assert _file_has_cross_file_content(
            {"function_components": {"components": []}, "custom_hooks": {"customHooks": []}}
        ) is False
