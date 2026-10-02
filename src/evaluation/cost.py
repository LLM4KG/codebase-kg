"""Phase 2 (code generation) token and USD cost from the call logs (IJCKG revision WP9).

Every Phase 2 LLM and embedding call is logged to `experiment_logs/<run>/<condition>.jsonl`
with token usage, `call_purpose`, model, and (for OpenRouter) the provider that served it.
No record carries a price, so USD = tokens x the dated table below.

Prices are USD per 1M tokens (input, output):
- Claude Sonnet 4.6: Anthropic list price. WP1 matched it to the Anthropic console to the
  cent for extraction, the same key and model.
- Qwen3-Coder via OpenRouter: each call is priced at the provider that served it
  (`openrouter_provider`). Rates are the per-provider endpoint prices from
  `https://openrouter.ai/api/v1/models/qwen/qwen3-coder/endpoints`, fetched on
  `PRICES_FETCHED`, not at call time; OpenRouter's own fees are excluded. Cross-check
  against the OpenRouter activity page before quoting.
- text-embedding-3-large: OpenAI list price.

A (model, provider) pair missing from the table is an error, never a silent zero.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

PRICES_FETCHED = "2026-09-20"

# (model_id, openrouter_provider or None) -> (USD per 1M input, USD per 1M output)
PRICES: dict[tuple[str, str | None], tuple[float, float]] = {
    ("anthropic/claude-sonnet-4-6", None): (3.00, 15.00),
    ("openrouter/qwen/qwen3-coder", "Google"): (0.22, 1.80),
    ("openrouter/qwen/qwen3-coder", "DeepInfra"): (0.30, 1.00),
    ("openrouter/qwen/qwen3-coder", "Venice"): (0.35, 1.50),
    ("openrouter/qwen/qwen3-coder", "Novita"): (0.38, 1.55),
    ("openrouter/qwen/qwen3-coder", "Alibaba"): (0.975, 4.875),
    ("text-embedding-3-large", None): (0.13, 0.0),
}

MODEL_LABEL = {
    "anthropic/claude-sonnet-4-6": "Claude Sonnet 4.6",
    "openrouter/qwen/qwen3-coder": "Qwen3-Coder",
    "text-embedding-3-large": "text-embedding-3-large",
}


class UnpricedCall(KeyError):
    pass


def call_cost(record: dict) -> float:
    """USD for one logged call. Mock and zero-token calls cost 0."""
    usage = record.get("usage") or {}
    tin, tout = usage.get("input_tokens") or 0, usage.get("output_tokens") or 0
    if tin == 0 and tout == 0:
        return 0.0
    key = (record.get("model_id"), record.get("openrouter_provider"))
    if key not in PRICES:
        raise UnpricedCall(f"no price for model={key[0]!r} provider={key[1]!r}")
    pin, pout = PRICES[key]
    return tin / 1e6 * pin + tout / 1e6 * pout


def _prompt_text(record: dict) -> str:
    prompt = record.get("prompt")
    if isinstance(prompt, list):
        return "\n".join(str(m.get("content", "")) if isinstance(m, dict) else str(m) for m in prompt)
    return str(prompt or "")


def match_task(record: dict, specs: dict[str, str]) -> str | None:
    """The task whose statement appears in the call's prompt.

    Embedding records log labels (`<spec>`, file paths), not the text, so they
    match nothing and return None. A prompt matching several tasks is an error.
    """
    text = _prompt_text(record)
    hits = [t for t, spec in specs.items() if spec and spec in text]
    if len(hits) > 1:
        raise ValueError(f"prompt matches several tasks: {hits}")
    return hits[0] if hits else None


@dataclass
class Tally:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    usd: float = 0.0

    def add(self, record: dict, usd: float) -> None:
        usage = record.get("usage") or {}
        self.calls += 1
        self.input_tokens += usage.get("input_tokens") or 0
        self.output_tokens += usage.get("output_tokens") or 0
        self.usd += usd


@dataclass
class CostReport:
    # (run, model, condition, task, purpose) -> Tally; task None = not task-specific
    rows: dict[tuple, Tally] = field(default_factory=lambda: defaultdict(Tally))
    # (date, model, provider) -> Tally, for checking against provider dashboards
    by_day: dict[tuple, Tally] = field(default_factory=lambda: defaultdict(Tally))
    # (run, condition, task) -> number of generator calls (= candidates)
    candidates: dict[tuple, int] = field(default_factory=lambda: defaultdict(int))

    def add(self, run: str, record: dict, task: str | None) -> None:
        usd = call_cost(record)
        purpose = record.get("call_purpose")
        cond = record.get("condition_id")
        self.rows[(run, record.get("model_id"), cond, task, purpose)].add(record, usd)
        usage = record.get("usage") or {}
        if (usage.get("input_tokens") or 0) or (usage.get("output_tokens") or 0):
            # Only billed calls: mock-generator records (0 tokens) never reached an API.
            day = str(record.get("timestamp", ""))[:10]
            self.by_day[(day, record.get("model_id"), record.get("openrouter_provider"))].add(record, usd)
        if purpose == "generator":
            self.candidates[(run, cond, task)] += 1


def by_generator_model(
    report: CostReport, generator_models: list[str]
) -> tuple[dict[tuple, dict[str, Tally]], dict[tuple, int]]:
    """Regroup a report's rows under each run's *generator* model.

    Returns `(agg, candidates)` keyed by `(generator_model, condition, task)`,
    where `task=None` is the all-tasks total. Embedding calls, which have no
    task, count once in that total, not twice.
    """
    gen_model = {run: model for (run, model, *_rest) in report.rows if model in generator_models}
    agg: dict[tuple, dict[str, Tally]] = defaultdict(lambda: defaultdict(Tally))
    for (run, model, cond, task, purpose), t in report.rows.items():
        gm = gen_model[run]
        for key in {(gm, cond, None), (gm, cond, task)}:
            slot = agg[key][purpose]
            slot.calls += t.calls
            slot.input_tokens += t.input_tokens
            slot.output_tokens += t.output_tokens
            slot.usd += t.usd
    candidates: dict[tuple, int] = defaultdict(int)
    for (run, cond, task), n in report.candidates.items():
        for key in {(gen_model[run], cond, None), (gen_model[run], cond, task)}:
            candidates[key] += n
    return agg, candidates
