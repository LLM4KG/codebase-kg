"""`pipeline pilot` Typer sub-app: run the validation pilot / calibrate timeouts."""

from __future__ import annotations

import asyncio
import logging
import os

import typer
from rich.console import Console
from rich.table import Table

from src.generation.edit_formats import known_formats
from src.generation.orchestrator import (
    CONDITIONS,
    KNOWN_CONDITIONS,
    RUN_TASKS,
    RunIdInUseError,
    run_pilot,
)
from src.generation.calibrate import calibrate_timeouts
from src.retrieval.config import load_condition_config
from src.harness.runner import QUARANTINED_MODES

pilot_app = typer.Typer(help="Phase 2 validation pilot (Work item 4/5).")
console = Console()
logger = logging.getLogger(__name__)


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    for noisy in ("httpx", "litellm", "neo4j"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _preflight_keys(run_name: str) -> None:
    """Fail loud when a real (non-mock) run is missing its provider key."""
    needed = "OPENROUTER_API_KEY" if "qwen" in run_name or "deepseek" in run_name else "ANTHROPIC_API_KEY"
    if not os.environ.get(needed):
        console.print(
            f"[red]Missing {needed} in the environment for run '{run_name}'.[/red]\n"
            f"Set it in .env / the shell, or use --mock (and --mock-retrieval) for an "
            f"offline dry run."
        )
        raise typer.Exit(1)


def _preflight_dense_key(conditions: tuple[str, ...]) -> None:
    """The dense condition embeds with OpenAI in every leg, mock or not.

    Without this, a cold embedding cache turns every dense candidate into a
    mid-run `harness_error`, and the run id is spent.

    Asks each condition TOML which retriever it dispatches to rather than matching
    the literal `"text_emb_3_large"`: WP12's `text_emb_3_large_matched` is the same
    embedder under a different id, and a name test would have waved it through to a
    cold cache.
    """
    dense = [c for c in conditions if load_condition_config(c).retriever == "text_emb_3_large"]
    if dense and not os.environ.get("OPENAI_API_KEY"):
        console.print(
            f"[red]Missing OPENAI_API_KEY for condition(s): {', '.join(dense)}.[/red]\n"
            "Dense retrieval embeds with OpenAI whatever the generator model, and in "
            "--mock runs too. Set it in .env / the shell."
        )
        raise typer.Exit(1)


@pilot_app.command("run")
def run(
    run_name: str = typer.Option(
        "claude_primary", "--run", help=f"Run config name. Known: {list(RUN_TASKS)}"
    ),
    n: int = typer.Option(5, help="Candidates per (task, condition)."),
    mock: bool = typer.Option(
        False, "--mock", help="Mock generator: emit each task's reference diff (no tokens/keys)."
    ),
    mock_retrieval: bool = typer.Option(
        False,
        "--mock-retrieval",
        help="kg_augmented returns empty context — skips Memgraph + classifier LLM call.",
    ),
    concurrency: int = typer.Option(2, help="Max concurrent candidates."),
    output_format: str = typer.Option(
        None,
        "--output-format",
        help=(
            f"Override the run's generator output format. One of: "
            f"{', '.join(known_formats())}. Omit to use the run config."
        ),
    ),
    conditions: str = typer.Option(
        None,
        "--conditions",
        help=f"Comma-separated conditions to run. Default: {','.join(CONDITIONS)}.",
    ),
    tasks: str = typer.Option(
        None,
        "--tasks",
        help="Comma-separated subset of the run's tasks (e.g. P2). Default: all of them.",
    ),
    run_id: str = typer.Option(
        None,
        "--run-id",
        help=(
            "Name the output directories under harness_results/, candidate_artifacts/ "
            "and experiment_logs/. Defaults to the run config's run_id. Use an "
            "archival name (e.g. claude_primary_2026-07-30_reeval) so a leg is not "
            "renamed after the fact."
        ),
    ),
    verbose: bool = typer.Option(False, "-v", "--verbose"),
) -> None:
    """Run one leg of the validation pilot."""
    _setup_logging(verbose)
    if not mock:
        _preflight_keys(run_name)

    if output_format is not None and output_format not in known_formats():
        console.print(
            f"[red]Unknown --output-format {output_format!r}. "
            f"Known: {', '.join(known_formats())}[/red]"
        )
        raise typer.Exit(1)

    selected = tuple(c.strip() for c in conditions.split(",")) if conditions else CONDITIONS
    unknown = [c for c in selected if c not in KNOWN_CONDITIONS]
    if unknown:
        console.print(
            f"[red]Unknown condition(s): {', '.join(unknown)}. "
            f"Known: {', '.join(KNOWN_CONDITIONS)}[/red]"
        )
        raise typer.Exit(1)
    _preflight_dense_key(selected)

    try:
        results = asyncio.run(
            run_pilot(
                run_name,
                n=n,
                mock=mock,
                mock_retrieval=mock_retrieval,
                concurrency=concurrency,
                output_format=output_format,
                conditions=selected,
                run_id=run_id,
                tasks=tuple(t.strip() for t in tasks.split(",")) if tasks else None,
            )
        )
    except (RunIdInUseError, ValueError) as exc:
        # Raised before any candidate runs, so nothing has been written yet.
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    # Stage alone is misleading in two directions. A quarantined candidate
    # (`recount_c0`, `whole_file_elided`) was applied without its placement or
    # completeness being verified, so its stage may describe code the model did
    # not write. And `diff_apply_fail` conflates "couldn't count lines" with
    # "invented a path" with "invented the code" — the distinction the pilot
    # most needed and did not have. Break out both axes.
    # Name the output directory, not just the config, when they differ — that is
    # where someone has to look for these numbers.
    label = run_name if not run_id or run_id == run_name else f"{run_name} → {run_id}"
    table = Table(title=f"Pilot run '{label}' — {len(results)} candidates")
    table.add_column("condition")
    table.add_column("stage")
    table.add_column("apply_mode")
    table.add_column("apply_reason")
    table.add_column("count", justify="right")
    counts: dict[tuple[str, str, str, str], int] = {}
    for r in results:
        key = (r.condition, r.stage.value, r.apply_mode or "—", r.apply_reason or "—")
        counts[key] = counts.get(key, 0) + 1
    for (condition, stage, mode, reason), c in sorted(counts.items()):
        label = f"[yellow]{mode}[/yellow]" if mode in QUARANTINED_MODES else mode
        table.add_row(condition, stage, label, reason, str(c))
    console.print(table)

    quarantined = [r for r in results if r.apply_mode in QUARANTINED_MODES]
    if quarantined:
        modes = ", ".join(sorted({r.apply_mode or "" for r in quarantined}))
        console.print(
            f"[yellow]{len(quarantined)}/{len(results)} candidates applied via "
            f"an unverified tier ({modes}) — the edit was NOT confirmed to land "
            f"where or as the model intended. Report these separately; do not "
            f"fold them into pass counts.[/yellow]"
        )


@pilot_app.command("calibrate")
def calibrate(
    tasks: list[str] = typer.Option(
        None, "--task", help="Task ids to calibrate (default: P1 P2 P3)."
    ),
    repeats: int = typer.Option(3, help="Reference-patch runs per task."),
    verbose: bool = typer.Option(False, "-v", "--verbose"),
) -> None:
    """Measure reference-patch runtimes and write conditions/timeouts.toml (WI5)."""
    _setup_logging(verbose)
    task_ids = tasks or ["P1", "P2", "P3"]
    timeouts = asyncio.run(calibrate_timeouts(task_ids, repeats=repeats))

    table = Table(title="Calibrated candidate timeouts")
    table.add_column("task")
    table.add_column("timeout (ms)", justify="right")
    for task_id, ms in timeouts.items():
        table.add_row(task_id, str(ms))
    console.print(table)
