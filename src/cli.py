"""Typer CLI app — extract, export, status, import commands."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="pipeline",
    help="Knowledge Graph extraction pipeline for React.js codebases.",
    add_completion=False,
)
console = Console()


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Quiet noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("litellm").setLevel(logging.WARNING)
    logging.getLogger("neo4j").setLevel(logging.WARNING)


@app.command()
def extract(
    repo: str | None = typer.Option(None, help="Path to the cloned React.js repository"),
    project: str | None = typer.Option(None, help="Project name from pipeline.toml [projects] table"),
    exclude_paths: list[str] | None = typer.Option(None, "--exclude-paths", help="Repo-relative path prefixes to exclude"),
    model: str | None = typer.Option(None, help="Override LLM model"),
    reset: bool = typer.Option(False, help="Reset checkpoint and re-extract from scratch"),
    verbose: bool = typer.Option(False, "-v", "--verbose", help="Enable debug logging"),
) -> None:
    """Run the full extraction pipeline on a React.js repository."""
    _setup_logging(verbose)

    from src.config import get_settings

    settings = get_settings()
    resolved_exclude: list[str] = []
    resolved_aliases: dict[str, str] = {}
    resolved_base_url: str = ""

    if project:
        project_cfg = settings.projects.get(project)
        if project_cfg is None:
            console.print(f"[red]Unknown project '{project}'. Check [projects] in pipeline.toml.[/red]")
            raise typer.Exit(1)
        repo = repo or project_cfg.repo_path
        resolved_exclude = project_cfg.exclude_paths
        resolved_aliases = project_cfg.aliases
        resolved_base_url = project_cfg.base_url
    elif repo is None:
        console.print("[red]Provide --repo or --project.[/red]")
        raise typer.Exit(1)

    # CLI --exclude-paths overrides project config
    if exclude_paths:
        resolved_exclude = exclude_paths

    if model:
        settings.llm.model = model

    try:
        resolved_repo = settings.resolve_repo_path(repo)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    from src.extraction.pipeline import run_pipeline
    asyncio.run(run_pipeline(str(resolved_repo), reset=reset, exclude_paths=resolved_exclude, aliases=resolved_aliases, base_url=resolved_base_url))


@app.command()
def status(
    verbose: bool = typer.Option(False, "-v", "--verbose"),
) -> None:
    """Show current graph database statistics."""
    _setup_logging(verbose)

    from src.graph.connection import run_query, get_driver
    from src.graph import queries as Q

    try:
        get_driver()
    except Exception as e:
        console.print(f"[red]Cannot connect to Memgraph: {e}[/red]")
        console.print("Make sure Memgraph is running: docker compose up -d")
        raise typer.Exit(1)

    # Node counts
    table = Table(title="Node Counts")
    table.add_column("Label", style="cyan")
    table.add_column("Count", style="green", justify="right")

    try:
        nodes = run_query(Q.COUNT_NODES_BY_LABEL)
        for row in nodes:
            table.add_row(str(row["label"]), str(row["count"]))
        console.print(table)
    except Exception as e:
        console.print(f"[yellow]Could not query nodes: {e}[/yellow]")

    # Relationship counts
    rel_table = Table(title="Relationship Counts")
    rel_table.add_column("Type", style="cyan")
    rel_table.add_column("Count", style="green", justify="right")

    try:
        rels = run_query(Q.COUNT_RELATIONSHIPS)
        for row in rels:
            rel_table.add_row(str(row["type"]), str(row["count"]))
        console.print(rel_table)
    except Exception as e:
        console.print(f"[yellow]Could not query relationships: {e}[/yellow]")

    from src.graph.connection import close_driver
    close_driver()


@app.command(name="export")
def export_graph(
    output: str = typer.Option("./graph_export", help="Output directory"),
    format: str = typer.Option("cypherl", help="Export format (cypherl)"),
    verbose: bool = typer.Option(False, "-v", "--verbose"),
) -> None:
    """Export the knowledge graph to CYPHERL format."""
    _setup_logging(verbose)

    from src.graph.connection import run_query, close_driver

    output_path = Path(output)
    output_path.mkdir(parents=True, exist_ok=True)

    if format == "cypherl":
        try:
            results = run_query("DUMP DATABASE;")
            dump_path = output_path / "full_dump.cypherl"
            with open(dump_path, "w") as f:
                for record in results:
                    for val in record.values():
                        f.write(str(val) + "\n")
            console.print(f"[green]Exported to {dump_path}[/green]")
        except Exception as e:
            console.print(f"[red]Export failed: {e}[/red]")
            raise typer.Exit(1)

        # Write manifest
        from src.graph import queries as Q
        from src.extraction.provenance import read_provenance
        try:
            nodes = run_query(Q.COUNT_NODES_BY_LABEL)
            rels = run_query(Q.COUNT_RELATIONSHIPS)
            manifest = {
                "format": "cypherl",
                "nodes": {r["label"]: r["count"] for r in nodes},
                "relationships": {r["type"]: r["count"] for r in rels},
            }

            # Fold in the extraction record if this directory has one. Graphs
            # extracted before provenance existed still export a valid manifest.
            provenance = read_provenance(output_path)
            if provenance is not None:
                manifest["provenance"] = provenance
            else:
                console.print(
                    "[yellow]No extraction_provenance.json in output dir — "
                    "manifest will not record model or source revision.[/yellow]"
                )

            manifest_path = output_path / "manifest.json"
            manifest_path.write_text(json.dumps(manifest, indent=2))
            console.print(f"[green]Manifest written to {manifest_path}[/green]")
        except Exception:
            pass
    else:
        console.print(f"[red]Unknown format: {format}[/red]")
        raise typer.Exit(1)

    close_driver()


@app.command(name="import")
def import_graph(
    input: str = typer.Option(..., help="Path to CYPHERL file to import"),
    verbose: bool = typer.Option(False, "-v", "--verbose"),
) -> None:
    """Import a CYPHERL dump into Memgraph."""
    _setup_logging(verbose)

    from src.graph.connection import run_query_void, close_driver
    from src.graph.schema import ensure_schema

    input_path = Path(input)
    if not input_path.exists():
        console.print(f"[red]File not found: {input_path}[/red]")
        raise typer.Exit(1)

    ensure_schema()

    with open(input_path) as f:
        lines = f.readlines()

    count = 0
    errors = 0
    for line in lines:
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            run_query_void(line)
            count += 1
        except Exception as e:
            errors += 1
            if errors <= 5:
                logging.warning("Import error on line %d: %s", count + errors, e)

    console.print(f"[green]Imported {count} statements ({errors} errors)[/green]")
    close_driver()


# PHASE 2 — validation pilot (Work item 4/5): `pipeline pilot run|calibrate`
from src.generation.cli import pilot_app  # noqa: E402

app.add_typer(pilot_app, name="pilot")


if __name__ == "__main__":
    app()
