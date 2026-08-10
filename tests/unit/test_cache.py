"""Tests for LLM response cache."""

import tempfile
import pytest

from src.llm.cache import _make_key, get_cached, set_cached


class TestMakeKey:
    def test_deterministic(self):
        key1 = _make_key("code", "prompt", "model")
        key2 = _make_key("code", "prompt", "model")
        assert key1 == key2

    def test_different_inputs(self):
        key1 = _make_key("code_a", "prompt", "model")
        key2 = _make_key("code_b", "prompt", "model")
        assert key1 != key2

    def test_different_prompts(self):
        key1 = _make_key("code", "prompt_a", "model")
        key2 = _make_key("code", "prompt_b", "model")
        assert key1 != key2

    def test_different_models(self):
        key1 = _make_key("code", "prompt", "model_a")
        key2 = _make_key("code", "prompt", "model_b")
        assert key1 != key2


class TestCacheGetSet:
    def test_cache_miss(self):
        result = get_cached("nonexistent_code_xyz", "prompt", "model")
        assert result is None

    def test_cache_roundtrip(self):
        code = "unique_test_code_for_cache_roundtrip"
        prompt_id = "test_prompt"
        model = "test_model"
        data = {"components": [{"name": "App"}]}

        set_cached(code, prompt_id, model, data)
        result = get_cached(code, prompt_id, model)
        assert result == data
