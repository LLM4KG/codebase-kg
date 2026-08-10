"""Write-before-return persistence for harness results.

Mirrors src/llm/logger.py's invariant: both a per-candidate `.json` (the literal
artifact Work item 4 reads as harness_output.json) and an appended `results.jsonl`
index are flushed to disk BEFORE run_candidate() returns.
"""

from __future__ import annotations

from pathlib import Path

from src.config import get_settings
from src.harness.models import HarnessResult


def _write_harness_result(
    result: HarnessResult, run_id: str, results_dir: Path | None = None
) -> None:
    root = results_dir or Path(get_settings().harness.results_dir)
    run_dir = root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    (run_dir / f"{result.candidate_id}.json").write_text(
        result.model_dump_json(indent=2), encoding="utf-8"
    )

    with open(run_dir / "results.jsonl", "a", encoding="utf-8") as f:
        f.write(result.model_dump_json() + "\n")
        f.flush()
