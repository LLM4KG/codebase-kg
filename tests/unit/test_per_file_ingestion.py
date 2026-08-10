"""Tests for per_file_ingestion utility functions."""

import pytest

from src.extraction.per_file_ingestion import is_custom_hook_name, check_is_literal


class TestIsCustomHookName:
    def test_valid_custom_hooks(self):
        assert is_custom_hook_name("useCart") is True
        assert is_custom_hook_name("useState") is True
        assert is_custom_hook_name("useEffect") is True
        assert is_custom_hook_name("useMyCustomHook") is True

    def test_invalid_names(self):
        assert is_custom_hook_name("use") is False  # too short
        assert is_custom_hook_name("usecart") is False  # lowercase after use
        assert is_custom_hook_name("App") is False
        assert is_custom_hook_name("handleClick") is False
        assert is_custom_hook_name("") is False

    def test_edge_cases(self):
        assert is_custom_hook_name("useA") is True  # minimum valid
        assert is_custom_hook_name("use1") is False  # digit, not uppercase


class TestCheckIsLiteral:
    def test_numeric_literals(self):
        assert check_is_literal("0") is True
        assert check_is_literal("42") is True
        assert check_is_literal("-1") is True
        assert check_is_literal("3.14") is True
        assert check_is_literal("-0.5") is True

    def test_string_literals(self):
        assert check_is_literal("'hello'") is True
        assert check_is_literal('"world"') is True
        assert check_is_literal("''") is True
        assert check_is_literal('""') is True

    def test_boolean_and_null_literals(self):
        assert check_is_literal("true") is True
        assert check_is_literal("false") is True
        assert check_is_literal("null") is True
        assert check_is_literal("undefined") is True

    def test_empty_collection_literals(self):
        assert check_is_literal("[]") is True
        assert check_is_literal("{}") is True

    def test_non_literals(self):
        assert check_is_literal("myVariable") is False
        assert check_is_literal("getData()") is False
        assert check_is_literal("props.value") is False
        assert check_is_literal("[1, 2, 3]") is False
        assert check_is_literal("{ key: value }") is False

    def test_empty_and_none(self):
        assert check_is_literal("") is False
        assert check_is_literal(None) is False

    def test_whitespace_handling(self):
        assert check_is_literal("  42  ") is True
        assert check_is_literal("  true  ") is True
