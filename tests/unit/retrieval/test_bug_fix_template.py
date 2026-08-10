"""Tests for the bug_fix Cypher template's hook-anchor support.

The pilot's P1 task is a hook-internal bug and its classifier anchor is
`useCartProducts`. The template filtered anchors to Function_Component and
Class_Component only, so it matched zero rows and rendered a 23-token context.
"""

from pathlib import Path

import pytest

from src.retrieval.assembler import (
    _build_bug_fix,
    _removal_steps,
    _truncate,
    _Assembly,
)
from src.retrieval.models import ComponentContext, ContextData
from src.retrieval.renderer import ContextRenderer

TEMPLATE = Path("src/retrieval/templates/bug_fix.cypher").read_text()


class TestTemplateShape:
    def test_accepts_custom_hook_as_anchor(self):
        assert "anchor:Custom_Hook" in TEMPLATE

    def test_still_accepts_component_anchors(self):
        assert "anchor:Function_Component" in TEMPLATE
        assert "anchor:Class_Component" in TEMPLATE

    def test_returns_hook_consumers(self):
        """A hook's blast radius is its callers — the analogue of directParents."""
        assert "usedByComponents" in TEMPLATE

    def test_returns_component_type_for_anchor_disambiguation(self):
        assert "labels(anchor)[0]" in TEMPLATE

    def test_routing_and_context_remain_excluded(self):
        """Deliberate scope choice for a localised fix; guard against drift."""
        assert "ROUTES_TO" not in TEMPLATE
        assert "CONSUMES_CONTEXT" not in TEMPLATE


class TestAssemblerHandlesHookAnchor:
    def _row(self, **overrides):
        row = {
            "componentName": "useCartProducts",
            "filePath": "src/contexts/cart-context/useCartProducts.ts",
            "componentType": "Custom_Hook",
            "acceptedProps": [],
            "libraryHooks": [{"name": "useContext", "source": "react"}],
            "customHooks": [],
            "stateVars": [],
            "classStateVars": [],
            "eventHandlers": [],
            "directParents": [],
            "delegatedHooks": [],
            "usedByComponents": [],
        }
        row.update(overrides)
        return row

    def test_hook_anchor_assembles_without_a_dedicated_branch(self, tmp_path):
        a = _Assembly(task_spec="fix the bug", task_type="bug_fix", project_name="react-shopping-cart")
        _build_bug_fix(a, [self._row()], tmp_path)

        assert len(a.anchors) == 1
        assert a.anchors[0].name == "useCartProducts"
        assert a.anchors[0].component_type == "Custom_Hook"

    def test_consumers_surface_as_neighbors(self, tmp_path):
        a = _Assembly(task_spec="fix the bug", task_type="bug_fix", project_name="react-shopping-cart")
        _build_bug_fix(
            a,
            [self._row(usedByComponents=[
                {"name": "Cart", "filePath": "src/components/Cart/Cart.tsx"},
            ])],
            tmp_path,
        )

        roles = [role for role, _cc in a.neighbors]
        names = [cc.name for _role, cc in a.neighbors]
        assert roles == ["used_by"]
        assert names == ["Cart"]

    def test_component_anchor_unaffected_by_the_new_key(self, tmp_path):
        """Component anchors get an empty usedByComponents; nothing should change."""
        a = _Assembly(task_spec="fix the bug", task_type="bug_fix", project_name="react-shopping-cart")
        _build_bug_fix(
            a,
            [self._row(
                componentName="Cart",
                componentType="Function_Component",
                filePath="src/components/Cart/Cart.tsx",
                directParents=[{"name": "App", "filePath": "src/App.tsx"}],
            )],
            tmp_path,
        )

        roles = [role for role, _cc in a.neighbors]
        assert roles == ["parent"]

    def test_null_collect_entries_are_dropped(self, tmp_path):
        """Memgraph's collect() over an unmatched OPTIONAL MATCH yields {name: null}."""
        a = _Assembly(task_spec="fix the bug", task_type="bug_fix", project_name="react-shopping-cart")
        _build_bug_fix(
            a,
            [self._row(usedByComponents=[{"name": None, "filePath": None}])],
            tmp_path,
        )
        assert a.neighbors == []


class TestHookConsumerTruncationPriority:
    """`used_by` must outrank event-handler notes.

    For a Custom_Hook anchor it *is* the blast radius, and a hook has no
    prop-passing parent to fall back on — but the bug_fix removal list opened with
    a blanket `neighbors.clear()`, so it went first of everything.
    """

    def _assembly(self):
        a = _Assembly(task_spec="fix the bug", task_type="bug_fix", project_name="react-shopping-cart")
        a.neighbors.append(("parent", ComponentContext(
            name="App", file_path="src/App.tsx", component_type="")))
        a.neighbors.append(("used_by", ComponentContext(
            name="Cart", file_path="src/components/Cart/Cart.tsx", component_type="")))
        a.droppable_notes.append("Cart event handlers: click→handleAddProduct")
        return a

    def test_parents_are_dropped_before_hook_consumers(self):
        steps = _removal_steps("bug_fix")
        a = self._assembly()
        steps[0](a)
        assert [role for role, _cc in a.neighbors] == ["used_by"]

    def test_event_handler_notes_are_dropped_before_hook_consumers(self):
        steps = _removal_steps("bug_fix")
        a = self._assembly()
        steps[0](a)
        steps[1](a)
        assert a.droppable_notes == []
        assert [role for role, _cc in a.neighbors] == ["used_by"]

    def test_hook_consumers_are_eventually_dropped(self):
        a = self._assembly()
        for step in _removal_steps("bug_fix"):
            step(a)
        assert a.neighbors == []

    def test_a_mild_overrun_drops_parents_and_keeps_consumers(self):
        """The end-to-end path: just over budget should cost the parent, not the
        hook's consumers."""
        a = self._assembly()
        budget = a.estimate() - 1  # one removal step is enough to fit

        _truncate(a, budget)

        assert a.estimate() <= budget
        assert [role for role, _cc in a.neighbors] == ["used_by"]


class TestNeighborRelationSurvivesMaterialization:
    """`materialize()` flattened (role, cc) to cc, so a hook's consumers rendered
    indistinguishably from a component's prop-passing parents."""

    def test_relation_is_carried_onto_the_rendered_neighbor(self):
        a = _Assembly(task_spec="fix", task_type="bug_fix", project_name="p")
        a.neighbors.append(("used_by", ComponentContext(
            name="Cart", file_path="src/components/Cart/Cart.tsx", component_type="")))

        data = a.materialize()
        assert [c.relation for c in data.neighbor_components] == ["used_by"]

    def test_anchors_have_no_relation(self):
        a = _Assembly(task_spec="fix", task_type="bug_fix", project_name="p")
        a.anchors.append(ComponentContext(
            name="useCartProducts", file_path="h.ts", component_type="Custom_Hook"))

        assert a.materialize().target_components[0].relation == ""

    def test_format_a_labels_the_relation(self):
        """The renderer must actually use it, or the field is decoration."""
        rendered = ContextRenderer().render("A", ContextData(
            task_spec="fix",
            task_type="bug_fix",
            project_name="react-shopping-cart",
            target_components=[ComponentContext(
                name="useCartProducts",
                file_path="src/contexts/cart-context/useCartProducts.ts",
                component_type="Custom_Hook")],
            neighbor_components=[ComponentContext(
                name="Cart",
                file_path="src/components/Cart/Cart.tsx",
                component_type="",
                relation="used_by")],
        ))
        assert "calls this hook" in rendered
