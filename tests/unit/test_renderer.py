"""Tests for the format-pluggable context renderer."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.retrieval.models import ComponentContext, ContextData
from src.retrieval.renderer import ContextRenderer, GENERATION_TEMPLATES_DIR


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_component(
    name: str = "ProductCard",
    file_path: str = "src/components/ProductCard.jsx",
    source_code: str | None = "function ProductCard({ title }) { return <div>{title}</div>; }",
    component_type: str = "Function_Component",
    **kwargs,
) -> ComponentContext:
    return ComponentContext(
        name=name,
        file_path=file_path,
        source_code=source_code,
        component_type=component_type,
        **kwargs,
    )


def _make_context_data(**overrides) -> ContextData:
    defaults = dict(
        task_spec="Add a quantity selector to the ProductCard component",
        task_type="feature_addition",
        target_components=[_make_component()],
        project_name="ShoppingCart",
        retriever_name="kg_augmented",
    )
    defaults.update(overrides)
    return ContextData(**defaults)


# ---------------------------------------------------------------------------
# Rendering tests (using the real prompts/generation/ directory)
# ---------------------------------------------------------------------------


class TestFormatARendering:
    def test_renders_successfully(self):
        renderer = ContextRenderer()
        data = _make_context_data()
        output = renderer.render("A", data)

        assert "ShoppingCart" in output
        assert "feature_addition" in output
        assert "ProductCard" in output
        assert "ProductCard.jsx" in output

    def test_source_code_in_output(self):
        renderer = ContextRenderer()
        data = _make_context_data()
        output = renderer.render("A", data)

        assert "function ProductCard({ title })" in output

    def test_props_in_output(self):
        renderer = ContextRenderer()
        comp = _make_component(props=[{"name": "title"}, {"name": "price"}])
        data = _make_context_data(target_components=[comp])
        output = renderer.render("A", data)

        assert "title" in output
        assert "price" in output

    def test_hooks_in_output(self):
        renderer = ContextRenderer()
        comp = _make_component(hooks=[{"name": "useState"}, {"name": "useEffect"}])
        data = _make_context_data(target_components=[comp])
        output = renderer.render("A", data)

        assert "useState" in output
        assert "useEffect" in output

    def test_state_variables_in_output(self):
        renderer = ContextRenderer()
        comp = _make_component(state_variables=[{"name": "count"}, {"name": "isOpen"}])
        data = _make_context_data(target_components=[comp])
        output = renderer.render("A", data)

        assert "count" in output
        assert "isOpen" in output

    def test_cross_cutting_notes(self):
        renderer = ContextRenderer()
        data = _make_context_data(
            cross_cutting_notes=[
                "ProductCard is rendered inside a React Router route",
                "CartContext provides the addToCart callback",
            ],
        )
        output = renderer.render("A", data)

        assert "Cross-Cutting Notes" in output
        assert "React Router route" in output
        assert "CartContext" in output

    def test_tsx_extension_detected(self):
        renderer = ContextRenderer()
        comp = _make_component(
            file_path="src/components/ProductCard.tsx",
            source_code="const ProductCard: FC = () => <div />;",
        )
        data = _make_context_data(target_components=[comp])
        output = renderer.render("A", data)

        assert "```tsx" in output

    def test_jsx_extension_detected(self):
        renderer = ContextRenderer()
        data = _make_context_data()
        output = renderer.render("A", data)

        assert "```jsx" in output


class TestNeighborComponents:
    def test_neighbor_metadata_in_output(self):
        renderer = ContextRenderer()
        neighbor = _make_component(
            name="CartSummary",
            file_path="src/components/CartSummary.jsx",
            source_code=None,
            props=[{"name": "items"}],
            hooks=[{"name": "useContext"}],
        )
        data = _make_context_data(neighbor_components=[neighbor])
        output = renderer.render("A", data)

        assert "Related Components" in output
        assert "CartSummary" in output
        assert "items" in output
        assert "useContext" in output

    def test_neighbor_source_not_rendered_when_none(self):
        renderer = ContextRenderer()
        neighbor = _make_component(
            name="CartSummary",
            file_path="src/components/CartSummary.jsx",
            source_code=None,
        )
        data = _make_context_data(neighbor_components=[neighbor])
        output = renderer.render("A", data)

        # The neighbor section should not contain a code block
        related_section = output.split("Related Components")[1] if "Related Components" in output else ""
        # No fenced code block for the neighbor
        assert "```jsx\nNone" not in related_section


class TestEmptyOptionals:
    def test_no_neighbors_no_section(self):
        renderer = ContextRenderer()
        data = _make_context_data(neighbor_components=[])
        output = renderer.render("A", data)

        assert "Related Components" not in output

    def test_no_cross_cutting_notes_no_section(self):
        renderer = ContextRenderer()
        data = _make_context_data(cross_cutting_notes=[])
        output = renderer.render("A", data)

        assert "Cross-Cutting Notes" not in output

    def test_no_props_no_label(self):
        renderer = ContextRenderer()
        comp = _make_component(props=[])
        data = _make_context_data(target_components=[comp])
        output = renderer.render("A", data)

        assert "**Props:**" not in output


class TestMultipleTargets:
    def test_two_target_components(self):
        renderer = ContextRenderer()
        comp1 = _make_component(name="ProductCard", file_path="src/ProductCard.jsx")
        comp2 = _make_component(name="CartItem", file_path="src/CartItem.jsx", source_code="function CartItem() {}")
        data = _make_context_data(target_components=[comp1, comp2])
        output = renderer.render("A", data)

        assert "ProductCard" in output
        assert "CartItem" in output
        assert "function CartItem()" in output


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------


class TestVariantValidation:
    @pytest.mark.parametrize("invalid", ["G", "a", "", "AB", "1"])
    def test_invalid_variant_raises(self, invalid: str):
        renderer = ContextRenderer()
        data = _make_context_data()
        with pytest.raises(ValueError, match="Invalid format_variant"):
            renderer.render(invalid, data)

    def test_missing_template_raises(self):
        renderer = ContextRenderer()
        data = _make_context_data()
        with pytest.raises(FileNotFoundError, match="Format B is not yet implemented"):
            renderer.render("B", data)


class TestTemplateDispatch:
    def test_variant_a_uses_format_a_template(self, tmp_path: Path):
        """Verify dispatch is filename-based, not hardcoded."""
        (tmp_path / "format_a.jinja2").write_text("CUSTOM_A: {{ project_name }}")
        renderer = ContextRenderer(template_dir=tmp_path)
        data = _make_context_data()
        output = renderer.render("A", data)

        assert "CUSTOM_A: ShoppingCart" == output.strip()

    def test_custom_template_dir(self, tmp_path: Path):
        (tmp_path / "format_a.jinja2").write_text("custom: {{ task_type }}")
        renderer = ContextRenderer(template_dir=tmp_path)
        data = _make_context_data()
        output = renderer.render("A", data)

        assert "custom: feature_addition" == output.strip()
