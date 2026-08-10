#!/usr/bin/env python3
"""Read the account's real rate-limit ceilings, then size `llm.phase2_call_delay`.

Phase 5 is ~4,200 generations. The pilot legs ran unthrottled and hit no limit,
but recorded no limit *headers* either — so "we hit nothing at 40 candidates"
was the only available evidence, and it says nothing about how close it came.
The pilot's measured peak was 24,133 input tokens/min, which is either ~80% of
the ceiling or ~5% of it depending on the account's tier. Guessing that is the
one thing this script exists to avoid.

Costs ~1 output token per provider: the probe is a `max_tokens=1` call whose
*headers* are the payload. The response body is discarded.

Usage:
    uv run python scripts/rate_limit_probe.py
    uv run python scripts/rate_limit_probe.py --json
    uv run python scripts/rate_limit_probe.py --concurrency 2 --mean-input-tokens 3500
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.llm.logger import _extract_rate_limit  # noqa: E402

# ── Defaults, all measured rather than assumed ───────────────────────────────
# Source: experiment_logs/claude_primary_2026-07-30_search_replace/*.jsonl,
# 61 calls over 745 s at --concurrency 2 with phase2_call_delay = 0.0.
DEFAULT_CONCURRENCY = 2          # src/generation/cli.py:59
DEFAULT_MEAN_INPUT_TOKENS = 3500  # KG-A worst case; P2 measured 3,453
DEFAULT_P50_LATENCY_S = 9.1       # p50 across the same 61 calls
HEADROOM = 0.7                    # 30% spare for burst + tenacity retries

PROBES = [
    # (label, litellm model string, env var holding the key)
    ("anthropic", "anthropic/claude-sonnet-4-6", "ANTHROPIC_API_KEY"),
    ("openrouter", "openrouter/qwen/qwen-2.5-coder-32b-instruct", "OPENROUTER_API_KEY"),
]


def load_env_file(path: Path = REPO_ROOT / ".env") -> None:
    """Populate os.environ from .env for keys not already set.

    `Settings` reads TOML + `PIPELINE_`-prefixed env vars, but LiteLLM reads the
    provider keys straight out of os.environ — so a shell that never exported
    .env has the keys on disk and invisible to the call.
    """
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


async def probe(model: str) -> dict[str, Any]:
    """One minimal call; return whatever rate-limit headers came back.

    LiteLLM prints a provider banner to stdout during resolution, which would
    corrupt `--json`; it is redirected to stderr for the duration of the call.
    """
    import contextlib

    import litellm

    # Without this LiteLLM prints a provider banner to stdout — including once at
    # interpreter exit, i.e. *after* the JSON document has been written.
    litellm.suppress_debug_info = True

    with contextlib.redirect_stdout(sys.stderr):
        response = await litellm.acompletion(
            model=model,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1,
            temperature=0.0,
        )
    return {"rate_limit": _extract_rate_limit(response) or {}}


def openrouter_key_limits() -> dict[str, Any]:
    """Ask OpenRouter directly — it returns no rate-limit response headers.

    `GET /api/v1/key` reports the key's own limit/usage, which is the only
    ceiling available for the Qwen and DeepSeek robustness legs.
    """
    import urllib.error
    import urllib.request

    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return {"skipped": "OPENROUTER_API_KEY not set"}
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/key",
        headers={"Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read()).get("data", {})
    except (urllib.error.URLError, ValueError, KeyError) as exc:
        return {"error": f"{type(exc).__name__}: {exc}"[:300]}


def derive_delay(
    itpm_limit: int | None,
    *,
    concurrency: int,
    mean_input_tokens: int,
    p50_latency_s: float,
) -> dict[str, Any]:
    """Apply the decision rule from the re-evaluation plan.

        required_rate = HEADROOM x ITPM_limit / mean_input_tokens
        delay         = max(0, concurrency / required_rate - p50_latency)

    The delay is applied per semaphore slot after a successful call
    (src/llm/logger.py), so steady-state request rate is
    `concurrency / (latency + delay)`.
    """
    if not itpm_limit:
        return {
            "input_tokens_limit": None,
            "verdict": "unknown — provider reported no input-token limit; "
                       "decide from the provider console, do not guess",
        }

    required_rate_per_min = HEADROOM * itpm_limit / mean_input_tokens
    seconds_per_call = 60.0 / required_rate_per_min
    delay = max(0.0, concurrency * seconds_per_call - p50_latency_s)

    observed_rate = concurrency / p50_latency_s * 60  # unthrottled steady state
    return {
        "input_tokens_limit": itpm_limit,
        "safe_requests_per_min": round(required_rate_per_min, 1),
        "unthrottled_requests_per_min": round(observed_rate, 1),
        "unthrottled_input_tokens_per_min": round(observed_rate * mean_input_tokens),
        "phase2_call_delay": round(delay, 1),
        "verdict": (
            "keep 0.0 — unthrottled demand fits inside the ceiling with headroom"
            if delay == 0.0
            else f"set phase2_call_delay = {delay:.1f}"
        ),
    }


async def main_async(args: argparse.Namespace) -> int:
    load_env_file()
    results: dict[str, Any] = {}

    for label, model, env_var in PROBES:
        if not os.environ.get(env_var):
            results[label] = {"skipped": f"{env_var} not set"}
            continue
        try:
            results[label] = await probe(model)
        except Exception as exc:  # a failed probe is a result, not a crash
            results[label] = {"error": f"{type(exc).__name__}: {exc}"[:300]}
            continue

        limits = results[label]["rate_limit"]
        results[label]["sizing"] = derive_delay(
            limits.get("input_tokens_limit"),
            concurrency=args.concurrency,
            mean_input_tokens=args.mean_input_tokens,
            p50_latency_s=args.p50_latency,
        )

    # OpenRouter sends no rate-limit headers at all, so the key endpoint is the
    # only source of a ceiling for the open-model legs.
    results["openrouter_key_endpoint"] = openrouter_key_limits()

    if args.json:
        print(json.dumps(results, indent=2))
        return 0

    for label, data in results.items():
        print(f"\n=== {label}")
        if "skipped" in data:
            print(f"  skipped: {data['skipped']}")
            continue
        if "error" in data:
            print(f"  error: {data['error']}")
            continue
        if not data["rate_limit"]:
            print("  no rate-limit headers returned by this provider")
        for k, v in sorted(data["rate_limit"].items()):
            print(f"  {k:32} {v}")
        sizing = data.get("sizing", {})
        if sizing:
            print("  ── sizing ──")
            for k, v in sizing.items():
                print(f"  {k:32} {v}")
    print()
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--json", action="store_true")
    p.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    p.add_argument("--mean-input-tokens", type=int, default=DEFAULT_MEAN_INPUT_TOKENS)
    p.add_argument("--p50-latency", type=float, default=DEFAULT_P50_LATENCY_S)
    return asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
