"""SQLite-based checkpoint for resumable extraction progress."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

from src.config import get_settings

logger = logging.getLogger(__name__)


class CheckpointDB:
    """Tracks per-file extraction progress for resume capability."""

    def __init__(self, db_path: str | None = None, read_only: bool = False):
        """Open the checkpoint.

        `read_only=True` opens the SQLite file in `mode=ro` and skips both table
        creation and the schema migration. Inspection tools must use it: the
        migration runs on open, so a diagnostic that merely *reports* checkpoint
        state would otherwise mutate it — `preflight_reextraction.py` silently
        discarded 55 rows the first time it ran after the migration landed. A
        check that changes the thing it checks is the wrong shape, even when the
        rows are disposable.

        Raises `sqlite3.OperationalError` if the file does not exist; callers in
        read-only mode are expected to check first.
        """
        path = db_path or get_settings().pipeline.checkpoint_db
        self.read_only = read_only
        if read_only:
            self.conn = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
            return
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self._create_tables()

    def _create_tables(self) -> None:
        self._migrate_to_composite_key()
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS file_progress (
                file_path TEXT NOT NULL,
                project_id TEXT NOT NULL,
                stage TEXT NOT NULL DEFAULT 'pending',
                llm_results TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (file_path, project_id)
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS pipeline_state (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        self.conn.commit()

    def _migrate_to_composite_key(self) -> None:
        """Rebuild `file_progress` if it predates the (file_path, project_id) key.

        The original schema keyed on `file_path` alone. Combined with the
        `INSERT OR IGNORE` in `init_files`, a path present in two projects (say
        `src/index.tsx`) kept the first project's row forever: the second project
        never re-extracted that file, and scoping the queries by `project_id`
        made it invisible to *both*. `CREATE TABLE IF NOT EXISTS` cannot fix an
        existing table, so migrate explicitly.

        Rows are dropped rather than copied. This is a resume cache, not a record
        of truth — the stored `llm_results` are reproducible from the LLM cache,
        and every documented re-extraction runs with `--reset` anyway.
        """
        cursor = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='file_progress'"
        )
        if cursor.fetchone() is None:
            return

        pk_columns = [
            row[1] for row in self.conn.execute("PRAGMA table_info(file_progress)")
            if row[5]  # row[5] is the primary-key position, 0 when not part of the key
        ]
        if set(pk_columns) == {"file_path", "project_id"}:
            return

        logger.warning(
            "Migrating checkpoint to a (file_path, project_id) primary key; "
            "discarding %d stale row(s).",
            self.conn.execute("SELECT COUNT(*) FROM file_progress").fetchone()[0],
        )
        self.conn.execute("DROP TABLE file_progress")
        self.conn.commit()

    def init_files(self, project_id: str, file_paths: list[str]) -> None:
        """Register files for processing, skipping already-completed ones."""
        for fp in file_paths:
            self.conn.execute("""
                INSERT OR IGNORE INTO file_progress (file_path, project_id, stage)
                VALUES (?, ?, 'pending')
            """, (fp, project_id))
        self.conn.commit()

    def get_pending_files(self, project_id: str | None = None) -> list[str]:
        """Return file paths that haven't completed LLM extraction.

        Scope to `project_id` whenever the caller knows it. The table is shared
        across projects, so an unscoped query mixes them — see
        `get_completed_files` for why that matters.
        """
        if project_id is None:
            cursor = self.conn.execute(
                "SELECT file_path FROM file_progress "
                "WHERE stage != 'completed' ORDER BY file_path"
            )
        else:
            cursor = self.conn.execute(
                "SELECT file_path FROM file_progress "
                "WHERE stage != 'completed' AND project_id = ? ORDER BY file_path",
                (project_id,),
            )
        return [row[0] for row in cursor.fetchall()]

    def get_completed_files(self, project_id: str | None = None) -> list[str]:
        """Return file paths that have completed extraction.

        Scoping matters: `file_progress` holds every project ever extracted, keyed
        by `file_path` alone. Unscoped, extracting project B would load project A's
        stored `llm_results` into B's Stage 4 input — and because `init_files` uses
        `INSERT OR IGNORE`, a repo-relative path present in both projects (say
        `src/index.tsx`) would keep A's row and never re-extract it for B.
        """
        if project_id is None:
            cursor = self.conn.execute(
                "SELECT file_path FROM file_progress "
                "WHERE stage = 'completed' ORDER BY file_path"
            )
        else:
            cursor = self.conn.execute(
                "SELECT file_path FROM file_progress "
                "WHERE stage = 'completed' AND project_id = ? ORDER BY file_path",
                (project_id,),
            )
        return [row[0] for row in cursor.fetchall()]

    def _scope(self, project_id: str | None) -> tuple[str, tuple]:
        """Build the project-scoping clause shared by the per-file accessors.

        Every caller that knows its `project_id` must pass it: `file_path` alone
        is no longer unique, so an unscoped UPDATE would write across projects.
        """
        if project_id is None:
            return "", ()
        return " AND project_id = ?", (project_id,)

    def _set_stage(self, file_path: str, stage: str, project_id: str | None) -> None:
        clause, params = self._scope(project_id)
        self.conn.execute(
            "UPDATE file_progress SET stage = ?, updated_at = CURRENT_TIMESTAMP "
            f"WHERE file_path = ?{clause}",
            (stage, file_path, *params),
        )
        self.conn.commit()

    def mark_extracting(self, file_path: str, project_id: str | None = None) -> None:
        """Mark a file as currently being extracted."""
        self._set_stage(file_path, "extracting", project_id)

    def mark_completed(
        self, file_path: str, llm_results: dict | None = None, project_id: str | None = None
    ) -> None:
        """Mark a file as completed with optional LLM results."""
        results_json = json.dumps(llm_results) if llm_results else None
        clause, params = self._scope(project_id)
        self.conn.execute(
            "UPDATE file_progress SET stage = 'completed', llm_results = ?, "
            f"updated_at = CURRENT_TIMESTAMP WHERE file_path = ?{clause}",
            (results_json, file_path, *params),
        )
        self.conn.commit()

    def mark_failed(self, file_path: str, project_id: str | None = None) -> None:
        """Mark a file as failed."""
        self._set_stage(file_path, "failed", project_id)

    def get_llm_results(self, file_path: str, project_id: str | None = None) -> dict | None:
        """Retrieve stored LLM results for a completed file."""
        clause, params = self._scope(project_id)
        cursor = self.conn.execute(
            f"SELECT llm_results FROM file_progress WHERE file_path = ? AND stage = 'completed'{clause}",
            (file_path, *params),
        )
        row = cursor.fetchone()
        if row and row[0]:
            return json.loads(row[0])
        return None

    def set_state(self, key: str, value: str) -> None:
        """Store a pipeline state value."""
        self.conn.execute(
            "INSERT OR REPLACE INTO pipeline_state (key, value) VALUES (?, ?)",
            (key, value),
        )
        self.conn.commit()

    def get_state(self, key: str) -> str | None:
        """Retrieve a pipeline state value."""
        cursor = self.conn.execute(
            "SELECT value FROM pipeline_state WHERE key = ?", (key,)
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def get_progress_summary(self, project_id: str | None = None) -> dict:
        """Return a stage -> count summary, scoped to one project when given.

        Unscoped, the end-of-run `Completed:` line counts other projects' rows
        and overstates what this run actually did.
        """
        if project_id is None:
            cursor = self.conn.execute(
                "SELECT stage, COUNT(*) FROM file_progress GROUP BY stage"
            )
        else:
            cursor = self.conn.execute(
                "SELECT stage, COUNT(*) FROM file_progress WHERE project_id = ? GROUP BY stage",
                (project_id,),
            )
        return dict(cursor.fetchall())

    def get_project_summary(self) -> dict[str, dict]:
        """Return per-project stage counts: {project_id: {stage: count}}.

        Used by the pre-flight guard, which must report what the checkpoint holds
        across *all* projects — `--reset` wipes rows globally, so a scoped view
        would hide rows the next run is about to delete.

        Tolerates a missing table: in read-only mode `_create_tables` is skipped,
        so a checkpoint file that predates the table (or was never written to)
        must read as empty rather than raise. The legacy single-key schema has the
        same columns, so this reads correctly there too.
        """
        try:
            cursor = self.conn.execute(
                "SELECT project_id, stage, COUNT(*) FROM file_progress GROUP BY project_id, stage"
            )
        except sqlite3.OperationalError as exc:
            logger.debug("No file_progress table to summarise: %s", exc)
            return {}
        summary: dict[str, dict] = {}
        for project_id, stage, count in cursor.fetchall():
            summary.setdefault(project_id, {})[stage] = count
        return summary

    def reset(self) -> None:
        """Reset all progress (for re-extraction)."""
        self.conn.execute("DELETE FROM file_progress")
        self.conn.execute("DELETE FROM pipeline_state")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
