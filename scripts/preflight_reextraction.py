#!/usr/bin/env python3
"""Pre-flight guards for a re-extraction that reuses the LLM cache.

Reusing the cache is safe because it stores LLM *responses*, and every resolution
and ingestion fix re-runs from scratch on each extraction. Two things would break
that reasoning silently, so they are checked mechanically rather than by
discipline:

1. **Prompt drift.** The cache key is (file_content_hash, prompt_id, model) and
   excludes template contents. Editing an existing template in place returns
   responses cached from the *old* prompt — the edit appears to do nothing.
2. **Model drift.** A changed `llm.model` invalidates every key at once, turning
   an expected ~121-call run into a ~1,330-call one without any visible signal.

Also warns about the two states that make a re-run a silent no-op: a populated
checkpoint (Stage 2+3 is skipped entirely) and a non-empty graph database (MERGE
never deletes, so stale nodes survive into the new dump).

The checkpoint check is intentionally global: `--reset` wipes every project's rows,
so any completed row is one the next run will delete.

    uv run python scripts/preflight_reextraction.py
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

OK, WARN, FAIL = "PASS", "WARN", "FAIL"


def _print(status: str, title: str, detail: str = "") -> None:
    colour = {OK: "\033[32m", WARN: "\033[33m", FAIL: "\033[31m"}[status]
    print(f"{colour}[{status}]\033[0m {title}")
    for line in detail.splitlines():
        if line.strip():
            print(f"        {line}")


def check_prompt_templates_unmodified() -> str:
    """No existing *extraction* prompt may be modified; only new files are allowed.

    Scoped to the top level of `prompts/` for the same reason
    `compute_prompt_set_version` is: `prompts/generation/` holds Phase 2
    code-generation templates, which are rendered at retrieval time and never
    reach the LLM response cache. Editing one cannot produce a stale cache hit,
    so flagging it would block re-extraction for an unrelated reason.
    """
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "status", "--porcelain", "--", "prompts/"],
        capture_output=True, text=True,
    )
    modified, added = [], []
    for line in result.stdout.splitlines():
        code, path = line[:2], line[3:].strip()
        if not path.endswith(".jinja2"):
            continue
        if Path(path).parent != Path("prompts"):
            continue  # not an extraction prompt
        # '??' untracked and 'A ' staged-add are new templates — safe.
        (added if code.strip() in {"??", "A"} else modified).append(path)

    if modified:
        _print(
            FAIL, "Existing prompt templates modified",
            "The LLM cache key excludes template contents, so these edits will\n"
            "silently return responses cached from the old prompt text:\n"
            + "\n".join(f"  - {p}" for p in modified)
            + "\nAdd a new prompt_id instead, or clear the cache deliberately.",
        )
        return FAIL

    _print(
        OK, "No existing prompt template modified",
        ("New templates (safe, distinct prompt_id): " + ", ".join(added)) if added else "",
    )
    return OK


def check_model_matches_cache(sample: int = 2000) -> str:
    """The configured model must be the one the cache was built with."""
    try:
        import diskcache
        from src.config import get_settings
    except ImportError as exc:
        _print(WARN, "Could not check model against cache", str(exc))
        return WARN

    settings = get_settings()
    configured = settings.llm.model
    cache_dir = REPO_ROOT / settings.pipeline.cache_dir
    if not cache_dir.exists():
        _print(WARN, "No LLM cache present", f"{cache_dir} does not exist — expect a cold run.")
        return WARN

    cache = diskcache.Cache(str(cache_dir))
    models: dict[str, int] = {}
    for i, key in enumerate(cache):
        if i >= sample:
            break
        parts = str(key).split("::")
        if len(parts) >= 3:
            models["::".join(parts[2:])] = models.get("::".join(parts[2:]), 0) + 1

    if not models:
        _print(WARN, "LLM cache is empty", "Expect a full cold re-extraction.")
        return WARN

    dominant = max(models, key=models.get)
    breakdown = ", ".join(f"{m} ({n})" for m, n in sorted(models.items(), key=lambda kv: -kv[1]))
    if configured != dominant:
        _print(
            FAIL, "Configured model does not match the cache",
            f"configured: {configured}\ncache:      {breakdown}\n"
            "Every cache key would miss — this becomes a full cold re-run.",
        )
        return FAIL

    _print(OK, f"Model matches cache: {configured}", f"cache contents: {breakdown}")
    return OK


def check_checkpoint_empty() -> str:
    """A populated checkpoint makes the whole Stage 2+3 loop a no-op.

    Deliberately unscoped. `project_id` in the checkpoint is
    `sha256(absolute repo path)[:12]` (`programmatic.py:extract_project`), not the
    project *name* — an earlier version of this guard scoped by the name passed on
    the command line, matched nothing, and reported PASS against a table holding 55
    completed rows. Unscoped is also the correct semantics: `--reset` wipes rows
    globally, so any row here is a row the next run is about to delete.
    """
    try:
        from src.config import get_settings
        from src.extraction.checkpoint import CheckpointDB
    except ImportError as exc:
        _print(WARN, "Could not inspect checkpoint", str(exc))
        return WARN

    path = REPO_ROOT / get_settings().pipeline.checkpoint_db
    if not path.exists():
        _print(OK, "No checkpoint database — nothing to reset")
        return OK

    # read_only: this is a diagnostic. Opening for write would run the schema
    # migration as a side effect of merely reporting state.
    db = CheckpointDB(str(path), read_only=True)
    try:
        per_project = db.get_project_summary()
    finally:
        db.close()

    total_completed = sum(
        stages.get("completed", 0) for stages in per_project.values()
    )
    if total_completed:
        breakdown = "\n".join(
            f"  {pid}: {stages}" for pid, stages in sorted(per_project.items())
        )
        _print(
            WARN, f"Checkpoint holds {total_completed} completed file(s)",
            f"{breakdown}\n"
            "(project_id is a hash of the repo path, not the project name.)\n"
            "Run with --reset, or Stage 2+3 is skipped entirely: the new prompt\n"
            "never fires and ingestion changes never execute. The run will look\n"
            "successful and change nothing.",
        )
        return WARN

    _print(OK, "Checkpoint has no completed files")
    return OK


def check_database_empty() -> str:
    """MERGE never deletes; stale nodes survive into the new dump."""
    try:
        from src.graph.connection import run_query, close_driver
    except ImportError as exc:
        _print(WARN, "Could not inspect database", str(exc))
        return WARN

    try:
        rows = run_query("MATCH (n) RETURN count(n) AS c")
        count = rows[0]["c"] if rows else 0
    except Exception as exc:
        _print(WARN, "Could not connect to Memgraph", f"{exc}\nStart it: docker compose up -d")
        return WARN
    finally:
        try:
            close_driver()
        except Exception:
            pass

    if count:
        _print(
            WARN, f"Database is not empty ({count} nodes)",
            "MERGE never deletes, so nodes fixed by this change (e.g. orphan\n"
            "Library_Hooks) would survive into the export alongside the correct\n"
            "ones. Wipe first: docker compose down -v && docker compose up -d\n"
            "This is also required by the one-project-per-database constraint.",
        )
        return WARN

    _print(OK, "Database is empty")
    return OK


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    sys.path.insert(0, str(REPO_ROOT))

    print("Pre-flight — re-extraction with LLM cache reuse\n")
    results = [
        check_prompt_templates_unmodified(),
        check_model_matches_cache(),
        check_checkpoint_empty(),
        check_database_empty(),
    ]

    print()
    if FAIL in results:
        print("\033[31mBLOCKED\033[0m — resolve the FAIL items before re-extracting.")
        return 1
    if WARN in results:
        print("\033[33mPROCEED WITH CARE\033[0m — the WARN items need an explicit action "
              "(--reset, docker compose down -v).")
        return 0
    print("\033[32mREADY\033[0m — safe to re-extract with cache reuse.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
