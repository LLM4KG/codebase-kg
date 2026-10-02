"""Main orchestration: Stages 1→4 pipeline."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import signal
import sys
import time
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from src.config import get_settings
from src.graph.schema import ensure_schema
from src.graph import ingestion
from src.extraction.programmatic import (
    extract_project,
    extract_files,
    extract_libraries,
    write_file_manifest,
)
from src.extraction.checkpoint import CheckpointDB
from src.extraction.llm_extractor import extract_file, PROMPTS, CROSS_FILE_PROMPTS
from src.extraction.per_file_ingestion import ingest_file_results
from src.extraction.cross_file import run_cross_file_extraction
from src.extraction.provenance import build_provenance, write_provenance
from src.llm import extraction_log

logger = logging.getLogger(__name__)
console = Console()

# Graceful shutdown flag
_shutdown_requested = False


def _signal_handler(sig, frame):
    global _shutdown_requested
    _shutdown_requested = True
    console.print("\n[yellow]Shutdown requested. Finishing current file...[/yellow]")


async def run_pipeline(
    repo_path: str,
    reset: bool = False,
    exclude_paths: list[str] | None = None,
    aliases: dict[str, str] | None = None,
    base_url: str = "",
) -> None:
    """Run the full extraction pipeline on a React.js repository."""
    repo_root = Path(repo_path).resolve()

    settings = get_settings()
    output_dir = Path(settings.pipeline.raw_output_dir) / repo_root.name

    # Set up graceful shutdown
    signal.signal(signal.SIGINT, _signal_handler)

    # Initialize checkpoint
    checkpoint = CheckpointDB()
    if reset:
        checkpoint.reset()

    console.print(f"[bold blue]Pipeline: Processing {repo_root.name}[/bold blue]")
    console.print(f"  Model: {settings.llm.model}")
    console.print(f"  Concurrency: {settings.llm.concurrency}")

    # ── Stage 1: Programmatic Extraction ──
    console.print("\n[bold]Stage 1: Programmatic Extraction[/bold]")

    ensure_schema()

    project = extract_project(repo_root)
    if project is None:
        console.print("[red]Cannot proceed without package.json[/red]")
        sys.exit(1)

    project_id = project["projectId"]
    ingestion.ingest_project(project)
    console.print(f"  Project: {project['name']} ({project_id})")

    files = extract_files(repo_root, exclude_paths=exclude_paths)
    ingestion.ingest_files_batch(files, project_id)
    console.print(f"  Files: {len(files)}")

    libraries = extract_libraries(repo_root)
    ingestion.ingest_libraries_batch(libraries, project_id)
    console.print(f"  Libraries: {len(libraries)}")

    # Write manifest and raw outputs
    output_dir.mkdir(parents=True, exist_ok=True)

    # On a full re-extraction, drop raw outputs from previous runs. Without this,
    # files excluded by a later `exclude_paths` change linger and the on-disk
    # evidence no longer matches the manifest (takenote carried 6 such orphans).
    # Only on reset: a resume run legitimately keeps the completed files' outputs.
    raw_dir = output_dir / "raw_extractions"
    cross_file_raw_dir = output_dir / "raw_extractions_cross_file"
    if reset:
        for stale_dir in (raw_dir, cross_file_raw_dir):
            if stale_dir.exists():
                removed = len(list(stale_dir.glob("*.json")))
                shutil.rmtree(stale_dir)
                console.print(f"  Cleared {removed} stale raw outputs from {stale_dir.name}/")

    manifest_path = output_dir / "file_manifest.json"
    write_file_manifest(project_id, files, manifest_path)

    (output_dir / "project.json").write_text(json.dumps(project, indent=2))
    (output_dir / "files.json").write_text(json.dumps(files, indent=2))
    (output_dir / "libraries.json").write_text(
        json.dumps([(lib, dt) for lib, dt in libraries], indent=2)
    )

    file_paths = [f["filePath"] for f in files]
    checkpoint.init_files(project_id, file_paths)

    # Token-usage log (IJCKG WP0). Keyed on the repo directory name, like the
    # output dir, so the log is findable next to the graph it describes.
    run_log = extraction_log.ExtractionRunLog(repo_root.name, settings.llm.model)
    console.print(f"  Usage log: {run_log.path}")

    # ── Stage 2 + 3: LLM Extraction + Per-File Ingestion ──
    console.print("\n[bold]Stage 2+3: LLM Extraction & Per-File Ingestion[/bold]")

    pending = checkpoint.get_pending_files(project_id)
    if not pending:
        console.print("  All files already extracted (resume)")
        pending = []

    all_llm_results: dict[str, dict] = {}

    # Load already-completed results
    resumed_files = 0
    for fp in checkpoint.get_completed_files(project_id):
        results = checkpoint.get_llm_results(fp, project_id)
        if results:
            all_llm_results[fp] = results
            # Made no call in this run and so leaves no usage record: the run's
            # totals under-state the repo's cost, which provenance must say.
            resumed_files += 1

    stage_2_3_start = time.perf_counter()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Extracting files...", total=len(pending))

        for fp in pending:
            if _shutdown_requested:
                console.print("[yellow]Shutdown: saving checkpoint[/yellow]")
                break

            full_path = repo_root / fp
            if not full_path.exists():
                logger.warning("File not found: %s", full_path)
                checkpoint.mark_failed(fp, project_id)
                progress.advance(task)
                continue

            code = full_path.read_text(errors="replace")
            checkpoint.mark_extracting(fp, project_id)

            try:
                llm_results = await extract_file(fp, code, run_log=run_log)
                all_llm_results[fp] = llm_results

                # Stage 3: Ingest into graph
                ingest_file_results(
                    fp, llm_results, file_paths,
                    aliases=aliases, base_url=base_url,
                )

                # Save raw results
                raw_dir.mkdir(parents=True, exist_ok=True)
                safe_name = fp.replace("/", "_").replace("\\", "_")
                (raw_dir / f"{safe_name}.json").write_text(
                    json.dumps(llm_results, indent=2)
                )

                checkpoint.mark_completed(fp, llm_results, project_id)
            except Exception as e:
                logger.error("Failed processing %s: %s", fp, e)
                checkpoint.mark_failed(fp, project_id)

            progress.advance(task)
            progress.update(task, description=f"[cyan]{fp}[/cyan]")

    stage_2_3_s = time.perf_counter() - stage_2_3_start

    if _shutdown_requested:
        console.print("[yellow]Pipeline paused. Re-run to resume.[/yellow]")
        checkpoint.close()
        return

    stage_4_start = time.perf_counter()

    # ── Stage 4: Cross-File Resolution ──
    console.print("\n[bold]Stage 4: Cross-File Resolution[/bold]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Cross-file resolution...", total=None)

        def on_cross_file_progress(step: int, total: int, desc: str):
            progress.update(task, completed=step, total=total, description=f"[cyan]{desc}[/cyan]")

        await run_cross_file_extraction(
            repo_root, file_paths, all_llm_results,
            on_progress=on_cross_file_progress,
            aliases=aliases,
            base_url=base_url,
            raw_output_dir=cross_file_raw_dir,
            run_log=run_log,
        )

    stage_4_s = time.perf_counter() - stage_4_start

    # ── Provenance ──
    # Written after Stage 4 so it only exists for a run that completed. Records
    # the model, the prompt-template hash and the source revision, none of which
    # are recoverable from the dump itself.
    provenance = build_provenance(
        repo_root=repo_root,
        project_id=project_id,
        model=settings.llm.model,
        prompt_ids=[p[0] for p in PROMPTS] + [p[0] for p in CROSS_FILE_PROMPTS],
        file_count=len(file_paths),
        usage=extraction_log.summarize(
            run_log,
            call_delay_s=settings.llm.call_delay,
            files_resumed_from_checkpoint=resumed_files,
            wall_clock_s={"stage_2_3": stage_2_3_s, "stage_4": stage_4_s},
        ),
    )
    write_provenance(output_dir, provenance)
    usage = provenance["usage"]
    console.print(
        f"  Usage: {usage['calls_api']} API calls ({usage['api_attempts']} attempts, "
        f"{usage['calls_failed']} failed), {usage['calls_cache_hit']} cache hits, "
        f"{usage['input_tokens']:,} in / {usage['output_tokens']:,} out tokens"
        + ("" if usage["complete"] else
           " [yellow](incomplete: cache hits or resumed files — not a cost figure)[/yellow]")
    )
    console.print(
        f"  Provenance: model={provenance['extraction_model']} "
        f"prompts={provenance['prompt_set_version']} "
        f"repo={(provenance['repo_commit_sha'] or 'unknown')[:12]}"
        + (" [yellow](dirty tree)[/yellow]" if provenance.get("repo_dirty") else "")
    )

    # ── Summary ──
    console.print("\n[bold green]Pipeline complete![/bold green]")
    summary = checkpoint.get_progress_summary(project_id)
    console.print(f"  Completed: {summary.get('completed', 0)}")
    console.print(f"  Failed: {summary.get('failed', 0)}")
    console.print(f"  Output: {output_dir}")

    checkpoint.close()
