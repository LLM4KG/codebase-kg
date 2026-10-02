"""Tests for the BM25 baseline retriever (IJCKG revision WP2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.retrieval.assembler import _estimate_tokens
from src.retrieval.bm25_retriever import (
    BM25Retriever,
    LuceneBM25,
    _Doc,
    build_corpus,
    rank,
    select_within_budget,
    tokenize,
)
from src.retrieval.config import RetrievalConditionConfig

CFG = RetrievalConditionConfig(condition_id="bm25", retriever="bm25", format_variant="A")


def _write(repo: Path, rel: str, content: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


@pytest.fixture(autouse=True)
def _fresh_corpus_cache():
    build_corpus.cache_clear()
    yield
    build_corpus.cache_clear()


# --------------------------------------------------------------------------- #
# Tokenizer                                                                   #
# --------------------------------------------------------------------------- #

def test_tokenize_splits_camel_case_and_keeps_whole_identifier():
    assert tokenize("decreaseProductQuantity") == [
        "decreaseproductquantity", "decrease", "product", "quantity",
    ]


def test_tokenize_splits_acronyms_and_punctuation():
    assert tokenize("HTTPServer cart-context") == ["httpserver", "http", "server", "cart", "context"]


def test_tokenize_drops_stopwords_but_keeps_code_keywords():
    assert tokenize("Fix the bug in const return") == ["fix", "bug", "const", "return"]


def test_tokenize_drops_one_character_tokens():
    """`product's` -> `s` and `$0.00` -> `0` were among P1's query tokens."""
    assert tokenize("the product's price is $0.00 in v2Api") == [
        "product", "price", "00", "v2api", "api",
    ]


# --------------------------------------------------------------------------- #
# Ranking and budget fill                                                     #
# --------------------------------------------------------------------------- #

def _docs(*pairs: tuple[str, str]) -> tuple[_Doc, ...]:
    return tuple(_Doc(p, s) for p, s in pairs)


def test_lucene_idf_is_positive_and_decreases_with_document_frequency():
    """rank_bm25's own IDF floors words in > N/2 files at 0.25 * mean IDF, which on
    the real corpora exceeded rarer words' IDF (`src` 60/60 files: 0.74 vs `notes`
    26/60: 0.26). Lucene's form must be positive and strictly decreasing in n."""
    n_docs = 60
    corpus = [["common"] + (["mid"] if i < 26 else []) + (["rare"] if i < 3 else [])
              for i in range(n_docs)]
    idf = LuceneBM25(corpus).idf
    assert 0 < idf["common"] < idf["mid"] < idf["rare"]


def test_word_in_every_file_does_not_make_unrelated_files_score():
    """Every file here contains `src`; only one mentions the spec's real subject.
    Under the old floor all three scored > 0 and the zero-score rule never fired."""
    docs = _docs(
        ("src/a.ts", "src src src src"),
        ("src/b.ts", "src src"),
        ("src/trash.ts", "src restoreAllTrash trash"),
    )
    ranked = rank("restore trash in src", docs)
    assert ranked[0][0].path == "src/trash.ts"
    assert ranked[0][1] > 5 * ranked[1][1]


def test_rank_puts_the_file_with_the_spec_identifiers_first():
    docs = _docs(
        ("src/Header.tsx", "const Header = () => <h1>title</h1>"),
        ("src/useCartProducts.ts", "const decreaseProductQuantity = (p) => p.quantity - 1"),
        ("src/Footer.tsx", "const Footer = () => <footer/>"),
    )
    ranked = rank("Fix decreaseProductQuantity so quantity never reaches zero", docs)
    assert ranked[0][0].path == "src/useCartProducts.ts"
    assert ranked[0][1] > 0


def test_rank_uses_path_words():
    docs = _docs(
        ("src/contexts/cart-context/index.ts", "export {}"),
        ("src/other/index.ts", "export {}"),
        ("src/third/index.ts", "export {}"),
    )
    assert rank("the cart context", docs)[0][0].path == "src/contexts/cart-context/index.ts"


def test_rank_ties_are_ordered_by_path():
    docs = _docs(("src/b.ts", "zzz"), ("src/a.ts", "zzz"), ("src/c.ts", "other"))
    ranked = rank("nothing matches", docs)
    assert [d.path for d, _ in ranked] == ["src/a.ts", "src/b.ts", "src/c.ts"]


def test_fill_never_exceeds_budget_on_the_shared_estimator():
    ranked = [(_Doc(f"f{i}.ts", "word " * 1000), 10.0 - i) for i in range(10)]
    included, skipped, used = select_within_budget(ranked, "spec text", budget=7000)
    assert used <= 7000
    assert used == _estimate_tokens("spec text") + sum(_estimate_tokens(d.source) for d in included)
    assert len(included) == 5 and len(skipped) == 5  # 1,300 estimated tokens each


def test_fill_skips_an_oversize_file_and_continues():
    ranked = [
        (_Doc("huge.ts", "word " * 10000), 9.0),
        (_Doc("small.ts", "word " * 10), 5.0),
    ]
    included, skipped, _ = select_within_budget(ranked, "spec", budget=7000)
    assert [d.path for d in included] == ["small.ts"]
    assert skipped == ["huge.ts"]


def test_fill_excludes_zero_score_files():
    ranked = [(_Doc("hit.ts", "x"), 1.2), (_Doc("miss.ts", "y"), 0.0)]
    included, _, _ = select_within_budget(ranked, "spec", budget=7000)
    assert [d.path for d in included] == ["hit.ts"]


# --------------------------------------------------------------------------- #
# Corpus and end-to-end retrieve                                              #
# --------------------------------------------------------------------------- #

def test_corpus_is_the_kg_file_set_and_honours_exclude_paths(tmp_path):
    _write(tmp_path, "src/App.tsx", "const App = () => null")
    _write(tmp_path, "src/App.test.tsx", "test()")          # extraction filter
    _write(tmp_path, "node_modules/x/index.js", "x")         # excluded dir
    _write(tmp_path, "src/server/api.ts", "server")          # project exclude_paths
    _write(tmp_path, "README.md", "readme")                  # not a source extension
    paths = [d.path for d in build_corpus(str(tmp_path), ("src/server",))]
    assert paths == ["src/App.tsx"]


async def test_retrieve_renders_paths_and_source_and_records_metadata(tmp_path):
    # Four files, not two: BM25Okapi's IDF is log((N-n+0.5)/(n+0.5)), which is
    # exactly 0 for a term in 1 of 2 documents. Real corpora are 50-140 files.
    _write(tmp_path, "src/useCartProducts.ts", "const decreaseProductQuantity = () => 0")
    _write(tmp_path, "src/Header.tsx", "const Header = () => null")
    _write(tmp_path, "src/Footer.tsx", "const Footer = () => null")
    _write(tmp_path, "src/Logo.tsx", "const Logo = () => null")
    r = BM25Retriever(CFG, task_type="bug_fix", project_name="shop")

    result = await r.retrieve("Fix decreaseProductQuantity", "", tmp_path)

    assert "`src/useCartProducts.ts`" in result.context
    assert "const decreaseProductQuantity" in result.context
    assert "Header" not in result.context  # zero score: shares no token with the spec
    assert result.retriever_name == "bm25"
    assert result.total_token_count <= 7000
    md = result.metadata
    assert md["included_files"] == ["src/useCartProducts.ts"]
    assert md["ranked_top"][0]["path"] == "src/useCartProducts.ts"
    assert md["corpus_size"] == 4
    assert md["token_budget"] == 7000
    assert result.rounds[0].retrieved_files == ["src/useCartProducts.ts"]


async def test_retrieve_is_deterministic(tmp_path):
    for i in range(5):
        _write(tmp_path, f"src/C{i}.tsx", f"const cart{i} = 'cart'")
    r = BM25Retriever(CFG)
    a = await r.retrieve("cart", "", tmp_path)
    b = await r.retrieve("cart", "", tmp_path)
    assert a.context == b.context
    assert a.metadata == b.metadata


async def test_rendered_cap_drops_files_the_source_count_admitted(tmp_path):
    """Many one-word files: spec + source fits the budget easily, but each file adds
    a heading and a code fence when rendered. The first-fit fill alone admits them
    all; only the rendered-cap loop can bring the context back under budget. (The
    previous version of this test never reached the loop.)"""
    for i in range(30):
        _write(tmp_path, f"src/cart{i}.ts", "cart")
    for i in range(30):
        _write(tmp_path, f"src/other{i}.ts", "unrelated")
    budget = 120
    docs = build_corpus(str(tmp_path.resolve()), ())
    admitted, _, _ = select_within_budget(rank("cart", docs), "cart", budget)
    assert len(admitted) == 30  # the source count alone lets every match in

    result = await BM25Retriever(CFG, token_budget=budget).retrieve("cart", "", tmp_path)

    assert result.total_token_count <= budget
    kept = result.metadata["included_files"]
    assert 0 < len(kept) < 30
    dropped = [p for p in result.metadata["skipped_for_budget"] if p.startswith("src/cart")]
    assert len(kept) + len(dropped) == 30
    # Dropped from the bottom of the ranking: every kept file outranks every dropped one.
    order = [d.path for d, _ in rank("cart", docs)]
    assert max(order.index(p) for p in kept) < min(order.index(p) for p in dropped)
