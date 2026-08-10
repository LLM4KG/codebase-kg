"""Light WI5 timeout calibration, folded into WI4.

Run each task's *reference* patch through the harness a few times, measure
wall-clock runtime, and set the candidate timeout to 3x the 95th-percentile. This
runs before the pilot so candidate timeouts aren't contaminated by a too-tight
default. Reference patches need no KG — the harness only applies the diff + runs
tests in Docker.
"""

from __future__ import annotations

import logging
import math
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

from src.generation.orchestrator import load_reference_diff
from src.harness.models import HarnessStage
from src.harness.runner import run_candidate
from src.harness.tasks import load_pilot_task

logger = logging.getLogger(__name__)

TIMEOUTS_TOML = Path("conditions/timeouts.toml")
GATE_SECONDS = 60.0


def _percentile(values: list[float], pct: float) -> float:
    """Linear-interpolation percentile (pct in [0, 100])."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (pct / 100.0) * (len(ordered) - 1)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


async def calibrate_task(task_id: str, *, repeats: int = 3) -> tuple[int, list[float]]:
    """Run `task_id`'s reference patch `repeats` times; return (timeout_ms, durations)."""
    task = load_pilot_task(task_id)
    ref_diff = load_reference_diff(task_id)
    durations: list[float] = []
    for k in range(1, repeats + 1):
        result = await run_candidate(
            candidate_diff=ref_diff,
            task=task,
            condition="reference",
            model="reference",
            candidate_id=f"{task_id}__ref__n{k}",
            run_id="calibration",
        )
        durations.append(result.duration_ms)
        if result.stage is not HarnessStage.test_pass:
            logger.warning(
                "Reference patch for %s did NOT pass (stage=%s) on run %d",
                task_id,
                result.stage.value,
                k,
            )
        if result.duration_ms > GATE_SECONDS * 1000:
            logger.warning(
                "Reference patch for %s took %.1fs (>%.0fs gate)",
                task_id,
                result.duration_ms / 1000,
                GATE_SECONDS,
            )
    p95 = _percentile(durations, 95.0)
    timeout_ms = int(math.ceil(3 * p95))
    return timeout_ms, durations


async def calibrate_timeouts(
    task_ids: list[str], *, repeats: int = 3, out_path: Path = TIMEOUTS_TOML
) -> dict[str, int]:
    """Calibrate all tasks and write conditions/timeouts.toml. Returns the map."""
    timeouts: dict[str, int] = {}
    for task_id in task_ids:
        timeout_ms, durations = await calibrate_task(task_id, repeats=repeats)
        timeouts[task_id] = timeout_ms
        logger.info(
            "%s: durations=%s ms -> timeout=%d ms",
            task_id,
            [round(d) for d in durations],
            timeout_ms,
        )
    _write_timeouts_toml(timeouts, out_path)
    return timeouts


def _write_timeouts_toml(timeouts: dict[str, int], out_path: Path) -> None:
    """Write calibrated timeouts, merging with any existing values.

    Merging keeps a targeted recalibration (`--task P3`) from dropping other
    tasks' previously-calibrated values.
    """
    merged: dict[str, int] = {}
    if out_path.exists():
        with open(out_path, "rb") as f:
            merged.update(
                {str(k): int(v) for k, v in tomllib.load(f).get("timeouts", {}).items()}
            )
    merged.update(timeouts)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Candidate timeouts (ms) — WI5 calibration: 3x the 95th-pctile",
        "# reference-patch runtime per task. Regenerate: `pipeline pilot calibrate`.",
        "[timeouts]",
    ]
    for task_id in sorted(merged):
        lines.append(f'"{task_id}" = {merged[task_id]}')
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
