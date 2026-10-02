"""WP9 Phase 2 cost: pricing, task attribution, aggregation."""

import pytest

from src.evaluation.cost import (
    CostReport,
    UnpricedCall,
    by_generator_model,
    call_cost,
    match_task,
)

CLAUDE = "anthropic/claude-sonnet-4-6"
QWEN = "openrouter/qwen/qwen3-coder"
EMB = "text-embedding-3-large"
SPECS = {"P1": "Fix the cart total.", "P2": "Add a restore-all button."}


def rec(model, tin, tout, purpose="generator", cond="bm25", provider=None, prompt="", day="2026-09-19"):
    return {
        "model_id": model, "openrouter_provider": provider, "call_purpose": purpose,
        "condition_id": cond, "usage": {"input_tokens": tin, "output_tokens": tout},
        "prompt": [{"role": "user", "content": prompt}], "timestamp": f"{day}T10:00:00+00:00",
    }


def test_claude_is_priced_at_list_price():
    assert call_cost(rec(CLAUDE, 1_000_000, 100_000)) == pytest.approx(3.00 + 1.50)


def test_qwen_is_priced_at_the_provider_that_served_it():
    deepinfra = call_cost(rec(QWEN, 1_000_000, 1_000_000, provider="DeepInfra"))
    alibaba = call_cost(rec(QWEN, 1_000_000, 1_000_000, provider="Alibaba"))
    assert deepinfra == pytest.approx(1.30)
    assert alibaba == pytest.approx(5.85)


def test_embedding_output_tokens_none_is_fine():
    r = rec(EMB, 1_000_000, None, purpose="embedding_query")
    assert call_cost(r) == pytest.approx(0.13)


def test_unpriced_calls_raise_and_zero_token_calls_are_free():
    with pytest.raises(UnpricedCall):
        call_cost(rec(QWEN, 10, 10, provider="SomeNewHost"))
    assert call_cost(rec("mock/anything", 0, 0)) == 0.0


def test_match_task_by_statement_in_prompt():
    assert match_task(rec(CLAUDE, 1, 1, prompt="Task:\nAdd a restore-all button.\n..."), SPECS) == "P2"
    assert match_task(rec(EMB, 1, None, prompt="<spec>"), SPECS) is None
    with pytest.raises(ValueError, match="several tasks"):
        match_task(rec(CLAUDE, 1, 1, prompt="Fix the cart total. Add a restore-all button."), SPECS)


def test_aggregation_counts_untasked_embedding_calls_once():
    report = CostReport()
    report.add("claude_run", rec(CLAUDE, 1000, 100, cond="text_emb_3_large", prompt=SPECS["P1"]), "P1")
    report.add("claude_run", rec(CLAUDE, 2000, 100, cond="text_emb_3_large", prompt=SPECS["P2"]), "P2")
    report.add("claude_run", rec(EMB, 102, None, purpose="embedding_query", cond="text_emb_3_large"), None)
    agg, cands = by_generator_model(report, [CLAUDE, QWEN])
    total = agg[(CLAUDE, "text_emb_3_large", None)]
    assert total["embedding_query"].input_tokens == 102
    assert total["generator"].input_tokens == 3000
    assert cands[(CLAUDE, "text_emb_3_large", None)] == 2
    assert cands[(CLAUDE, "text_emb_3_large", "P1")] == 1


def test_classifier_cost_is_attributed_to_the_task_and_condition():
    report = CostReport()
    report.add("qwen_run", rec(QWEN, 500, 30, "classifier", "kg_augmented", "Venice", SPECS["P1"]), "P1")
    report.add("qwen_run", rec(QWEN, 1500, 300, "generator", "kg_augmented", "Venice", SPECS["P1"]), "P1")
    agg, cands = by_generator_model(report, [CLAUDE, QWEN])
    cell = agg[(QWEN, "kg_augmented", "P1")]
    assert set(cell) == {"classifier", "generator"}
    assert cands[(QWEN, "kg_augmented", "P1")] == 1


def test_dashboard_view_skips_mock_calls_and_splits_by_day_and_provider():
    report = CostReport()
    report.add("r", rec(CLAUDE, 0, 0), "P1")                       # mock generator
    report.add("r", rec(QWEN, 10, 10, provider="Google", day="2026-09-18"), "P1")
    report.add("r", rec(QWEN, 10, 10, provider="Venice", day="2026-09-18"), "P1")
    assert set(report.by_day) == {("2026-09-18", QWEN, "Google"), ("2026-09-18", QWEN, "Venice")}
