"""Tests for the dense (embedding) baseline retriever (IJCKG revision WP3).

`litellm.aembedding` is replaced by a deterministic bag-of-words embedder, so the
logger path (`logged_embedding_call`) runs for real and no API key is used.
"""

from __future__ import annotations

import asyncio
import json
import zlib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from src.llm import logger as llm_logger
from src.retrieval import dense_retriever as dense
from src.retrieval.bm25_retriever import _Doc, build_corpus, tokenize
from src.retrieval.config import RetrievalConditionConfig
from src.retrieval.dense_retriever import (
    DenseRetriever,
    EmbeddingCache,
    cache_key,
    rank_by_cosine,
)

CFG = RetrievalConditionConfig(
    condition_id="text_emb_3_large",
    retriever="text_emb_3_large",
    format_variant="A",
    retriever_params={"embedding_model": "fake-embed"},
)
DIM = 64


def _vector(text: str) -> list[float]:
    # Slot 0 is a shared component, as real embeddings have: every cosine is > 0,
    # so no file drops out for sharing no word with the spec (which BM25 does).
    vec = [1.0] + [0.0] * (DIM - 1)
    for tok in tokenize(text):
        vec[1 + zlib.crc32(tok.encode()) % (DIM - 1)] += 1.0
    return vec


@pytest.fixture
def api(monkeypatch, tmp_path):
    """Fake embedding API: records each request's inputs; logs go to tmp."""
    calls: list[list[str]] = []

    async def fake_aembedding(*, model, input):
        calls.append(list(input))
        await asyncio.sleep(0)  # a real request yields; lets concurrent retrieves interleave
        return SimpleNamespace(
            data=[{"index": i, "embedding": _vector(t), "object": "embedding"} for i, t in enumerate(input)],
            usage=SimpleNamespace(prompt_tokens=sum(len(t.split()) for t in input)),
            model=model,
        )

    monkeypatch.setattr(llm_logger.litellm, "aembedding", fake_aembedding)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    build_corpus.cache_clear()
    yield SimpleNamespace(calls=calls, log_dir=tmp_path / "logs", cache_root=tmp_path / "cache")
    build_corpus.cache_clear()


def _write(repo: Path, rel: str, content: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "shop"
    _write(repo, "src/useCartProducts.ts", "const decreaseProductQuantity = (p) => p.quantity - 1")
    _write(repo, "src/Header.tsx", "const Header = () => <h1>title</h1>")
    _write(repo, "src/Footer.tsx", "const Footer = () => <footer/>")
    _write(repo, "src/Logo.tsx", "const Logo = () => <img/>")
    return repo


def _retriever(api, **kw) -> DenseRetriever:
    return DenseRetriever(
        CFG, run_id="r1", project_name="shop", cache_root=api.cache_root, log_dir=api.log_dir, **kw
    )


SPEC = "Fix decreaseProductQuantity so the quantity never goes below one"


# --------------------------------------------------------------------------- #
# Ranking and cache                                                           #
# --------------------------------------------------------------------------- #

def test_rank_by_cosine_orders_by_similarity_then_path():
    docs = (_Doc("src/b.ts", ""), _Doc("src/a.ts", ""), _Doc("src/c.ts", ""))
    vecs = [np.array([1.0, 0.0]), np.array([1.0, 0.0]), np.array([0.0, 1.0])]
    ranked = rank_by_cosine(np.array([2.0, 0.1]), docs, vecs)
    assert [d.path for d, _ in ranked] == ["src/a.ts", "src/b.ts", "src/c.ts"]
    assert ranked[0][1] == pytest.approx(ranked[1][1])


def test_rank_by_cosine_is_scale_invariant_and_survives_a_zero_vector():
    docs = (_Doc("src/long.ts", ""), _Doc("src/empty.ts", ""))
    ranked = rank_by_cosine(np.array([1.0, 1.0]), docs, [np.array([10.0, 10.0]), np.zeros(2)])
    assert ranked[0] == (docs[0], pytest.approx(1.0))
    assert ranked[1][1] == 0.0


def test_cache_round_trips_float32_exactly_and_first_line_wins(tmp_path):
    path = tmp_path / "c.jsonl"
    v = [0.1, -1 / 3, 1e-8]
    EmbeddingCache(path).add([{"key": "k", "kind": "doc", "label": "a.ts", "batch": {"id": "b", "size": 1, "prompt_tokens": 3}, "vector": v}])
    EmbeddingCache(path).add([{"key": "k", "kind": "doc", "label": "a.ts", "batch": {"id": "b", "size": 1, "prompt_tokens": 3}, "vector": [9.0, 9.0, 9.0]}])
    loaded = EmbeddingCache(path).get("k")
    assert loaded.dtype == np.float32
    assert np.array_equal(loaded, np.asarray(v, dtype=np.float32))
    row = json.loads(path.read_text().splitlines()[0])
    assert row["kind"] == "doc" and row["label"] == "a.ts" and "embedding_b64" in row


def test_cache_key_depends_on_model_and_text():
    assert cache_key("m", "x") != cache_key("m", "y")
    assert cache_key("m1", "x") != cache_key("m2", "x")


# --------------------------------------------------------------------------- #
# retrieve()                                                                  #
# --------------------------------------------------------------------------- #

async def test_retrieve_ranks_the_matching_file_first_and_fills_the_budget(api, tmp_path):
    repo = _repo(tmp_path)
    result = await _retriever(api, task_type="bug_fix").retrieve(SPEC, "", repo)

    md = result.metadata
    assert md["ranked_top"][0]["path"] == "src/useCartProducts.ts"
    # No zero-score cut: every file fits the budget, so all four are included.
    assert md["included_files"][0] == "src/useCartProducts.ts"
    assert sorted(md["included_files"]) == sorted(d["path"] for d in md["ranked_top"])
    assert len(md["included_files"]) == 4
    assert "`src/useCartProducts.ts`" in result.context
    assert result.retriever_name == "dense"
    assert result.total_token_count <= 7000
    assert md["embedding_model"] == "fake-embed"
    assert md["cache_file"].endswith("shop/fake-embed.jsonl")
    assert (md["api_calls"], md["cache_hits"]) == (2, 0)  # index batch + query
    assert result.rounds[0].retrieved_files == md["included_files"]


async def test_embedded_documents_include_their_path(api, tmp_path):
    await _retriever(api).retrieve(SPEC, "", _repo(tmp_path))
    index_inputs, query_inputs = api.calls
    assert "src/Footer.tsx\nconst Footer = () => <footer/>" in index_inputs
    assert query_inputs == [SPEC]


async def test_second_retrieve_is_served_from_the_cache(api, tmp_path):
    repo = _repo(tmp_path)
    first = await _retriever(api).retrieve(SPEC, "", repo)
    second = await _retriever(api).retrieve(SPEC, "", repo)

    assert len(api.calls) == 2  # none from the second retrieve
    assert (second.metadata["api_calls"], second.metadata["cache_hits"]) == (0, 5)
    assert second.context == first.context
    assert second.metadata["ranked_top"] == first.metadata["ranked_top"]


async def test_only_changed_files_and_new_queries_are_embedded(api, tmp_path):
    repo = _repo(tmp_path)
    await _retriever(api).retrieve(SPEC, "", repo)
    _write(repo, "src/Logo.tsx", "const Logo = () => <svg/>")
    build_corpus.cache_clear()

    md = (await _retriever(api).retrieve(SPEC, "", repo)).metadata
    assert api.calls[2] == ["src/Logo.tsx\nconst Logo = () => <svg/>"]
    assert (md["api_calls"], md["cache_hits"]) == (1, 4)  # the spec is cached


async def test_cache_rows_carry_their_batch_so_the_index_can_be_costed(api, tmp_path, monkeypatch):
    monkeypatch.setattr(dense, "BATCH_SIZE", 3)
    repo = _repo(tmp_path)
    _write(repo, "src/Extra.tsx", "const Extra = () => null")
    md = (await _retriever(api).retrieve(SPEC, "", repo)).metadata

    rows = [json.loads(line) for line in (api.cache_root / "shop" / "fake-embed.jsonl").read_text().splitlines()]
    batches = {r["batch"]["id"]: r["batch"] for r in rows}
    assert sorted(b["size"] for b in batches.values()) == [1, 2, 3]
    assert all(sum(r["batch"]["id"] == bid for r in rows) == b["size"] for bid, b in batches.items())
    assert sum(b["prompt_tokens"] for b in batches.values()) == md["api_prompt_tokens"]


async def test_misses_are_sent_in_batches(api, tmp_path, monkeypatch):
    monkeypatch.setattr(dense, "BATCH_SIZE", 3)
    repo = _repo(tmp_path)
    _write(repo, "src/Extra.tsx", "const Extra = () => null")   # 5 docs -> batches of 3 + 2
    md = (await _retriever(api).retrieve(SPEC, "", repo)).metadata
    assert [len(c) for c in api.calls] == [3, 2, 1]
    assert md["api_calls"] == 3


async def test_each_api_call_is_logged_with_usage(api, tmp_path):
    await _retriever(api).retrieve(SPEC, "", _repo(tmp_path))
    records = [json.loads(line) for line in (api.log_dir / "r1" / "text_emb_3_large.jsonl").read_text().splitlines()]
    assert [r["call_purpose"] for r in records] == ["embedding_index", "embedding_query"]
    assert all(r["usage"]["input_tokens"] > 0 and r["usage"]["output_tokens"] is None for r in records)
    assert records[0]["model_provider"] == "openai"
    assert sorted(records[0]["prompt"][0]["content"]) == [
        "src/Footer.tsx", "src/Header.tsx", "src/Logo.tsx", "src/useCartProducts.ts",
    ]
    assert records[1]["prompt"][0]["content"] == ["<spec>"]


async def test_failed_call_is_logged_then_raised(api, tmp_path, monkeypatch):
    async def boom(*, model, input):
        raise ValueError("bad request")

    monkeypatch.setattr(llm_logger.litellm, "aembedding", boom)
    with pytest.raises(ValueError, match="bad request"):
        await _retriever(api).retrieve(SPEC, "", _repo(tmp_path))
    (record,) = [json.loads(line) for line in (api.log_dir / "r1" / "text_emb_3_large.jsonl").read_text().splitlines()]
    assert record["error"]["error_type"] == "ValueError"
    assert record["usage"] is None and record["call_purpose"] == "embedding_index"


async def test_short_response_is_logged_before_it_raises(api, tmp_path, monkeypatch):
    async def short(*, model, input):
        return SimpleNamespace(data=[{"index": 0, "embedding": [1.0, 0.0]}],
                               usage=SimpleNamespace(prompt_tokens=11), model=model)

    monkeypatch.setattr(llm_logger.litellm, "aembedding", short)
    with pytest.raises(RuntimeError, match="1 vectors for 4 inputs"):
        await _retriever(api).retrieve(SPEC, "", _repo(tmp_path))
    (record,) = [json.loads(line) for line in (api.log_dir / "r1" / "text_emb_3_large.jsonl").read_text().splitlines()]
    assert record["usage"]["input_tokens"] == 11  # the billed call is on record


async def test_missing_key_fails_loudly_only_when_the_api_is_needed(api, tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    await _retriever(api).retrieve(SPEC, "", repo)          # fills the cache
    monkeypatch.delenv("OPENAI_API_KEY")

    await _retriever(api).retrieve(SPEC, "", repo)          # fully cached: fine
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        await _retriever(api).retrieve("a spec never embedded", "", repo)
    assert len(api.calls) == 2


async def test_concurrent_candidates_share_one_call_per_text(api, tmp_path):
    repo = _repo(tmp_path)
    a, b = await asyncio.gather(
        _retriever(api).retrieve(SPEC, "", repo), _retriever(api).retrieve(SPEC, "", repo)
    )
    assert len(api.calls) == 2
    assert a.context == b.context
    lines = (api.cache_root / "shop" / "fake-embed.jsonl").read_text().splitlines()
    assert len(lines) == 5  # no duplicate rows


async def test_rendered_context_respects_a_small_budget(api, tmp_path):
    repo = _repo(tmp_path)
    for i in range(20):
        _write(repo, f"src/cart{i}.ts", "const cart = 'cart quantity'")
    result = await _retriever(api, token_budget=150).retrieve(SPEC, "", repo)
    assert result.total_token_count <= 150
    md = result.metadata
    assert 0 < len(md["included_files"]) < 24
    assert len(md["included_files"]) + len(md["skipped_for_budget"]) == 24


async def test_corpus_honours_exclude_paths(api, tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "src/server/api.ts", "const decreaseProductQuantity = 1")
    md = (await _retriever(api, exclude_paths=["src/server"]).retrieve(SPEC, "", repo)).metadata
    assert md["corpus_size"] == 4
    assert "src/server/api.ts" not in md["included_files"]


def test_cache_locks_are_per_loop_and_freed_with_it(tmp_path):
    import gc

    async def get():
        return dense._lock_for(tmp_path / "c.jsonl")

    loop_a = asyncio.new_event_loop()
    lock_a = loop_a.run_until_complete(get())
    assert loop_a.run_until_complete(get()) is lock_a       # shared within a loop
    loop_b = asyncio.new_event_loop()
    assert loop_b.run_until_complete(get()) is not lock_a   # never across loops
    loop_b.close()
    loop_a.close()
    n_before = len(dense._LOCKS)
    del loop_a, loop_b, lock_a
    gc.collect()
    assert len(dense._LOCKS) <= n_before - 2
