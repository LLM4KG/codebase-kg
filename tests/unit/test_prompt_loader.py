"""Tests for prompt template rendering."""

import pytest

from src.llm.prompt_loader import render_prompt


TEMPLATES = [
    "function_component.jinja2",
    "class_component.jinja2",
    "prop_and_event_handler.jinja2",
    "library_usage.jinja2",
    "state_variable_function.jinja2",
    "state_variable_class.jinja2",
    "context.jinja2",
    "composition_and_prop_flow.jinja2",
    "custom_hook_internal.jinja2",
    "context_provider_consumer.jinja2",
    "route_definition.jinja2",
]


class TestPromptLoader:
    @pytest.mark.parametrize("template", TEMPLATES)
    def test_template_renders(self, template):
        code = "const App = () => <div>Hello</div>;"
        result = render_prompt(template, code=code)
        assert code in result
        assert len(result) > len(code)

    @pytest.mark.parametrize("template", TEMPLATES)
    def test_no_unresolved_variables(self, template):
        code = "function MyComponent() { return <div />; }"
        result = render_prompt(template, code=code)
        assert "{{ " not in result
        assert " }}" not in result
