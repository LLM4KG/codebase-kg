"""Tests for checkpoint project scoping and provenance recording.

`file_progress` holds every project ever extracted. It was originally keyed on
`file_path` alone, so unscoped reads mixed projects: re-extracting project B would
load project A's stored `llm_results` into B's Stage 4 input. Scoping the queries
fixed the reads but left a second half of the bug — with `file_path` still the sole
primary key and `init_files` using `INSERT OR IGNORE`, a path shared by two
projects kept only the first project's row, making the file invisible to *both*
scoped queries. Hence the composite `(file_path, project_id)` key.
"""

import json
import sqlite3

import pytest

from src.extraction.checkpoint import CheckpointDB
from src.extraction.provenance import (
    build_provenance,
    compute_prompt_set_version,
    read_provenance,
    write_provenance,
)

PROJECT_A = "eff3cf336442"  # react-shopping-cart
PROJECT_B = "46e1e7c383ab"  # takenote


@pytest.fixture
def db(tmp_path):
    checkpoint = CheckpointDB(str(tmp_path / "checkpoint.db"))
    yield checkpoint
    checkpoint.close()


class TestCheckpointProjectScoping:
    def test_completed_files_scoped_to_project(self, db):
        db.init_files(PROJECT_A, ["src/components/Cart.tsx"])
        db.init_files(PROJECT_B, ["src/client/App.tsx"])
        db.mark_completed("src/components/Cart.tsx", {"function_components": {}})
        db.mark_completed("src/client/App.tsx", {"function_components": {}})

        assert db.get_completed_files(PROJECT_A) == ["src/components/Cart.tsx"]
        assert db.get_completed_files(PROJECT_B) == ["src/client/App.tsx"]

    def test_pending_files_scoped_to_project(self, db):
        db.init_files(PROJECT_A, ["a.tsx", "b.tsx"])
        db.init_files(PROJECT_B, ["c.tsx"])
        db.mark_completed("a.tsx", None)

        assert db.get_pending_files(PROJECT_A) == ["b.tsx"]
        assert db.get_pending_files(PROJECT_B) == ["c.tsx"]

    def test_unscoped_call_still_returns_everything(self, db):
        """Back-compat: the argument is optional and defaults to the old behaviour."""
        db.init_files(PROJECT_A, ["a.tsx"])
        db.init_files(PROJECT_B, ["c.tsx"])
        assert db.get_pending_files() == ["a.tsx", "c.tsx"]

    def test_other_project_completion_does_not_hide_pending_work(self, db):
        """The bug this scoping fixes.

        Project B is entirely unextracted. Unscoped, A's completed rows are
        irrelevant to B — but the old code read the whole table, so a fully
        complete A made B's Stage 2+3 loop look partially done and fed A's
        results into B's Stage 4.
        """
        db.init_files(PROJECT_A, ["a.tsx", "b.tsx"])
        db.mark_completed("a.tsx", {"stale": "from project A"})
        db.mark_completed("b.tsx", {"stale": "from project A"})
        db.init_files(PROJECT_B, ["c.tsx"])

        assert db.get_pending_files(PROJECT_B) == ["c.tsx"]
        assert db.get_completed_files(PROJECT_B) == []

    def test_reset_clears_all_projects(self, db):
        """`--reset` is global; documented rather than changed."""
        db.init_files(PROJECT_A, ["a.tsx"])
        db.init_files(PROJECT_B, ["c.tsx"])
        db.reset()
        assert db.get_pending_files() == []


class TestSharedFilePaths:
    """The half of the scoping bug that survived scoping the queries.

    `src/index.tsx` exists in both pilot repos in principle; the two projects
    happen not to collide today, which is exactly why this needs a test rather
    than a live check.
    """

    SHARED = "src/index.tsx"

    def test_both_projects_keep_their_own_row(self, db):
        db.init_files(PROJECT_A, [self.SHARED])
        db.init_files(PROJECT_B, [self.SHARED])

        assert db.get_pending_files(PROJECT_A) == [self.SHARED]
        assert db.get_pending_files(PROJECT_B) == [self.SHARED]

    def test_completing_one_project_leaves_the_other_pending(self, db):
        db.init_files(PROJECT_A, [self.SHARED])
        db.init_files(PROJECT_B, [self.SHARED])
        db.mark_completed(self.SHARED, {"from": "A"}, PROJECT_A)

        assert db.get_completed_files(PROJECT_A) == [self.SHARED]
        assert db.get_completed_files(PROJECT_B) == []
        assert db.get_pending_files(PROJECT_B) == [self.SHARED]

    def test_stored_results_do_not_leak_across_projects(self, db):
        db.init_files(PROJECT_A, [self.SHARED])
        db.init_files(PROJECT_B, [self.SHARED])
        db.mark_completed(self.SHARED, {"from": "A"}, PROJECT_A)
        db.mark_completed(self.SHARED, {"from": "B"}, PROJECT_B)

        assert db.get_llm_results(self.SHARED, PROJECT_A) == {"from": "A"}
        assert db.get_llm_results(self.SHARED, PROJECT_B) == {"from": "B"}

    def test_marking_failed_is_scoped(self, db):
        db.init_files(PROJECT_A, [self.SHARED])
        db.init_files(PROJECT_B, [self.SHARED])
        db.mark_failed(self.SHARED, PROJECT_A)

        assert db.get_pending_files(PROJECT_A) == [self.SHARED]  # failed != completed
        assert db.get_progress_summary(PROJECT_A) == {"failed": 1}
        assert db.get_progress_summary(PROJECT_B) == {"pending": 1}


class TestProgressSummary:
    def test_summary_is_scoped_to_one_project(self, db):
        db.init_files(PROJECT_A, ["a.tsx", "b.tsx"])
        db.init_files(PROJECT_B, ["c.tsx"])
        db.mark_completed("a.tsx", None, PROJECT_A)

        assert db.get_progress_summary(PROJECT_A) == {"completed": 1, "pending": 1}
        assert db.get_progress_summary(PROJECT_B) == {"pending": 1}

    def test_unscoped_summary_still_spans_projects(self, db):
        db.init_files(PROJECT_A, ["a.tsx"])
        db.init_files(PROJECT_B, ["c.tsx"])
        assert db.get_progress_summary() == {"pending": 2}

    def test_project_summary_breaks_down_by_project(self, db):
        """What the pre-flight guard reports; it must never be scoped."""
        db.init_files(PROJECT_A, ["a.tsx"])
        db.init_files(PROJECT_B, ["c.tsx"])
        db.mark_completed("a.tsx", None, PROJECT_A)

        assert db.get_project_summary() == {
            PROJECT_A: {"completed": 1},
            PROJECT_B: {"pending": 1},
        }


class TestLegacySchemaMigration:
    """`CREATE TABLE IF NOT EXISTS` cannot fix an existing table."""

    def _write_legacy_db(self, path):
        conn = sqlite3.connect(str(path))
        conn.execute("""
            CREATE TABLE file_progress (
                file_path TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                stage TEXT NOT NULL DEFAULT 'pending',
                llm_results TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute(
            "INSERT INTO file_progress (file_path, project_id, stage) VALUES (?, ?, 'completed')",
            ("src/index.tsx", PROJECT_A),
        )
        conn.commit()
        conn.close()

    def test_legacy_db_is_migrated_to_the_composite_key(self, tmp_path):
        path = tmp_path / "checkpoint.db"
        self._write_legacy_db(path)

        db = CheckpointDB(str(path))
        try:
            pk = {row[1] for row in db.conn.execute("PRAGMA table_info(file_progress)") if row[5]}
            assert pk == {"file_path", "project_id"}
            # Stale rows are discarded — this is a resume cache, not a record of truth.
            assert db.get_completed_files() == []

            db.init_files(PROJECT_A, ["src/index.tsx"])
            db.init_files(PROJECT_B, ["src/index.tsx"])
            assert db.get_pending_files(PROJECT_B) == ["src/index.tsx"]
        finally:
            db.close()

    def test_read_only_open_does_not_migrate(self, tmp_path):
        """A diagnostic must not mutate the thing it reports on.

        The migration runs on open, so `preflight_reextraction.py` discarded 55
        rows the first time it ran — while doing nothing but reporting.
        """
        path = tmp_path / "checkpoint.db"
        self._write_legacy_db(path)

        db = CheckpointDB(str(path), read_only=True)
        try:
            assert db.get_project_summary() == {PROJECT_A: {"completed": 1}}
            pk = {row[1] for row in db.conn.execute("PRAGMA table_info(file_progress)") if row[5]}
            assert pk == {"file_path"}, "read-only open must leave the legacy schema alone"
        finally:
            db.close()

        # Still legacy, still populated, for the next writer to migrate.
        conn = sqlite3.connect(str(path))
        assert conn.execute("SELECT COUNT(*) FROM file_progress").fetchone()[0] == 1
        conn.close()

    def test_read_only_open_rejects_writes(self, tmp_path):
        path = tmp_path / "checkpoint.db"
        self._write_legacy_db(path)

        db = CheckpointDB(str(path), read_only=True)
        try:
            with pytest.raises(sqlite3.OperationalError):
                db.reset()
        finally:
            db.close()

    def test_migration_is_idempotent(self, tmp_path):
        path = tmp_path / "checkpoint.db"
        self._write_legacy_db(path)

        CheckpointDB(str(path)).close()
        db = CheckpointDB(str(path))
        try:
            db.init_files(PROJECT_A, ["a.tsx"])
            db.mark_completed("a.tsx", {"kept": True}, PROJECT_A)
        finally:
            db.close()

        # A second open must not wipe rows written under the new schema.
        db = CheckpointDB(str(path))
        try:
            assert db.get_llm_results("a.tsx", PROJECT_A) == {"kept": True}
        finally:
            db.close()


class TestProvenance:
    def test_prompt_set_version_is_stable_and_short(self):
        version = compute_prompt_set_version()
        assert version != "unknown"
        assert len(version) == 12
        assert version == compute_prompt_set_version()

    def test_prompt_set_version_changes_when_a_template_changes(self, tmp_path):
        (tmp_path / "a.jinja2").write_text("hello {{ code }}")
        before = compute_prompt_set_version(tmp_path)
        (tmp_path / "a.jinja2").write_text("goodbye {{ code }}")
        assert compute_prompt_set_version(tmp_path) != before

    def test_prompt_set_version_changes_when_a_template_is_added(self, tmp_path):
        (tmp_path / "a.jinja2").write_text("hello")
        before = compute_prompt_set_version(tmp_path)
        (tmp_path / "b.jinja2").write_text("world")
        assert compute_prompt_set_version(tmp_path) != before

    def test_missing_prompts_dir_does_not_raise(self, tmp_path):
        assert compute_prompt_set_version(tmp_path / "nope") == "unknown"

    def test_generation_templates_do_not_affect_the_extraction_fingerprint(self, tmp_path):
        """`prompts/generation/` holds Phase 2 code-gen templates, not extraction
        prompts. A recursive walk swept them in, so editing `format_a.jinja2`
        changed the recorded fingerprint of KGs it never touched."""
        (tmp_path / "function_component.jinja2").write_text("extract {{ code }}")
        generation = tmp_path / "generation"
        generation.mkdir()
        (generation / "format_a.jinja2").write_text("## Project Context")

        before = compute_prompt_set_version(tmp_path)
        (generation / "format_a.jinja2").write_text("## Project Context (revised)")
        assert compute_prompt_set_version(tmp_path) == before

        # ...while a real extraction template still moves it.
        (tmp_path / "function_component.jinja2").write_text("extract differently {{ code }}")
        assert compute_prompt_set_version(tmp_path) != before

    def test_live_prompt_set_excludes_generation_subdir(self, tmp_path):
        """Guards the real `prompts/` tree, not just a synthetic one.

        Copies only the top-level templates into an isolated directory; if the
        live computation matches, nothing from `generation/` contributed.
        """
        import shutil

        from src.extraction.provenance import _PROMPTS_DIR

        assert (_PROMPTS_DIR / "generation").is_dir(), "fixture assumption changed"
        for path in _PROMPTS_DIR.glob("*.jinja2"):
            shutil.copy(path, tmp_path / path.name)

        assert compute_prompt_set_version() == compute_prompt_set_version(tmp_path)

    def test_build_and_roundtrip(self, tmp_path):
        provenance = build_provenance(
            repo_root=tmp_path,
            project_id=PROJECT_A,
            model="anthropic/claude-sonnet-4-6",
            prompt_ids=["custom_hooks", "function_components"],
            file_count=56,
        )
        assert provenance["extraction_model"] == "anthropic/claude-sonnet-4-6"
        assert provenance["prompt_ids"] == ["custom_hooks", "function_components"]
        assert provenance["file_count"] == 56
        assert "extracted_at" in provenance

        write_provenance(tmp_path, provenance)
        assert read_provenance(tmp_path) == provenance

    def test_non_git_repo_records_null_sha_without_raising(self, tmp_path):
        provenance = build_provenance(tmp_path, PROJECT_A, "m", [], 0)
        assert provenance["repo_commit_sha"] is None

    def test_read_returns_none_when_absent(self, tmp_path):
        """Pre-provenance exports must still produce a manifest."""
        assert read_provenance(tmp_path) is None

    def test_read_returns_none_on_corrupt_file(self, tmp_path):
        (tmp_path / "extraction_provenance.json").write_text("{not json")
        assert read_provenance(tmp_path) is None
