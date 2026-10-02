"""Token-usage log for Phase 1 extraction calls (IJCKG revision WP0).

Phase 2 calls are logged by `src/llm/logger.py`, which wraps raw LiteLLM.
Extraction cannot use that path: it goes through Instructor, whose validate-and-
re-ask loop is part of how the committed graphs were built. So extraction keeps
its call path, and this module only records what those calls cost.

One JSONL record per *logical* call (one prompt on one file), written to
`experiment_logs/<run_id>/extraction.jsonl` and flushed before the pipeline moves
on. Unlike Phase 2 records, a record carries no prompt or response text: the
prompt is rebuilt from file + template + `prompt_set_version`, and the response
is already in `raw_extractions*/`.

Two ways a run can look cheaper than it was, both surfaced by `summarize()`:
a diskcache hit (logged, with zero tokens) and a checkpoint resume (the skipped
files leave no record at all, so the caller must report how many there were).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.llm.logger import _get_log_dir, _write_log_record

LOG_FILENAME = "extraction.jsonl"

STAGE_CALL_PURPOSE = {
    "per_file": "extraction_per_file",
    "cross_file": "extraction_cross_file",
}

_TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)


def _zero_usage() -> dict[str, int]:
    return {field: 0 for field in _TOKEN_FIELDS}


def _sum_usage(entries: list[dict]) -> dict[str, int]:
    total = _zero_usage()
    for entry in entries:
        for field in _TOKEN_FIELDS:
            total[field] += entry.get(field) or 0
    return total


class ExtractionRunLog:
    """Appends one record per extraction call for a single `pipeline extract` run."""

    def __init__(
        self,
        project: str,
        model: str,
        *,
        log_dir: Path | None = None,
        run_id: str | None = None,
    ) -> None:
        self.project = project
        self.model = model
        self.log_dir = log_dir or _get_log_dir()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        self.run_id = run_id or f"extract_{project}_{stamp}"

    @property
    def path(self) -> Path:
        return self.log_dir / self.run_id / LOG_FILENAME

    def _write(self, record: dict) -> None:
        _write_log_record(
            record, self.run_id, Path(LOG_FILENAME).stem, log_dir=self.log_dir
        )

    def _base(self, stage: str, prompt_id: str, file_path: str) -> dict:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "project": self.project,
            "stage": stage,
            "call_purpose": STAGE_CALL_PURPOSE[stage],
            "prompt_id": prompt_id,
            "file_path": file_path,
            "model_id": self.model,
        }

    def record_cache_hit(self, stage: str, prompt_id: str, file_path: str) -> None:
        """A call served from diskcache: nothing billed, but it must still show up,
        so a cached run cannot pass for a cheap one."""
        self._write({
            **self._base(stage, prompt_id, file_path),
            "cache_hit": True,
            "attempts": 0,
            "usage": _zero_usage(),
            "attempt_usage": [],
            "latency_ms": 0.0,
            "rate_limit": None,
            "error": None,
        })

    def record_call(
        self,
        stage: str,
        prompt_id: str,
        file_path: str,
        *,
        attempt_usage: list[dict],
        latency_ms: float,
        error: BaseException | None = None,
    ) -> None:
        """A call that reached the API. `attempt_usage` is the `usage_sink` filled
        by `extract_structured`, one entry per billed attempt."""
        last_rate_limit = next(
            (e.get("rate_limit") for e in reversed(attempt_usage) if e.get("rate_limit")),
            None,
        )
        self._write({
            **self._base(stage, prompt_id, file_path),
            "cache_hit": False,
            "attempts": len(attempt_usage),
            "usage": _sum_usage(attempt_usage),
            "attempt_usage": [
                {k: v for k, v in e.items() if k != "rate_limit"} for e in attempt_usage
            ],
            "latency_ms": latency_ms,
            "rate_limit": last_rate_limit,
            "error": None if error is None else {
                "error_type": type(error).__name__,
                "message": str(error)[:2000],
            },
        })


def read_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def summarize(
    run_log: ExtractionRunLog,
    *,
    call_delay_s: float,
    files_resumed_from_checkpoint: int,
    wall_clock_s: dict[str, float],
) -> dict:
    """Build the provenance `usage` block from the run's own JSONL.

    Totals are recomputed from disk rather than kept in memory, so they equal the
    log by construction. `complete` is true only when no call came from the cache
    and no file was skipped by a resume — only such runs may be quoted as a
    repo's extraction cost.
    """
    records = read_records(run_log.path)

    def _bucket(rows: list[dict]) -> dict:
        api = [r for r in rows if not r["cache_hit"]]
        usage = _sum_usage([r["usage"] for r in api])
        return {
            "calls_api": len(api),
            "calls_cache_hit": len(rows) - len(api),
            "calls_failed": sum(1 for r in api if r["error"] is not None),
            "api_attempts": sum(r["attempts"] for r in api),
            **usage,
            "api_latency_s": round(sum(r["latency_ms"] for r in api) / 1000, 3),
        }

    by_stage = {
        stage: _bucket([r for r in records if r["stage"] == stage])
        for stage in STAGE_CALL_PURPOSE
    }
    by_prompt = {
        prompt_id: _bucket([r for r in records if r["prompt_id"] == prompt_id])
        for prompt_id in sorted({r["prompt_id"] for r in records})
    }
    totals = _bucket(records)

    return {
        "run_id": run_log.run_id,
        "log_path": str(run_log.path),
        "model": run_log.model,
        "call_delay_s": call_delay_s,
        "complete": totals["calls_cache_hit"] == 0 and files_resumed_from_checkpoint == 0,
        "files_resumed_from_checkpoint": files_resumed_from_checkpoint,
        **totals,
        "wall_clock_s": {k: round(v, 3) for k, v in wall_clock_s.items()},
        "by_stage": by_stage,
        "by_prompt": by_prompt,
    }
