"""Preflight checks in `pipeline pilot run` (no run starts, nothing is written)."""

from __future__ import annotations

import pytest
import typer

from src.generation.cli import _preflight_dense_key


def test_dense_without_openai_key_exits_before_the_run(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(typer.Exit):
        _preflight_dense_key(("floor", "text_emb_3_large"))


def test_dense_with_key_and_other_conditions_without_key_pass(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _preflight_dense_key(("floor", "bm25"))
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    _preflight_dense_key(("text_emb_3_large",))
