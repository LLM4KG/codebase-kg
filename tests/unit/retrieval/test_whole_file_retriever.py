"""Unit tests for the whole-file oracle retriever.

This is the contentful non-KG arm. Its whole job is to put real source in the
prompt, so the tests are mostly about that actually happening — the pilot's
`floor` arm looked wired correctly too, and shipped 436-token prompts with no
code in them for 15 candidates.
"""

from __future__ import annotations

import textwrap

import pytest
import yaml

from src.retrieval.config import RetrievalConditionConfig
from src.retrieval.whole_file_retriever import WholeFileRetriever, oracle_files


@pytest.fixture
def tasks_dir(tmp_path):
    d = tmp_path / "tasks"
    d.mkdir()
    (d / "T1.yaml").write_text(
        yaml.safe_dump(
            {
                "task_id": "T1",
                "task_type": "refactoring",
                "files_modified": ["src/App.tsx"],
                "files_created": ["src/hooks/useThing.ts"],
            }
        )
    )
    return d


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    (r / "src").mkdir(parents=True)
    (r / "src" / "App.tsx").write_text("export const App = () => <div />\n")
    return r


def _config():
    return RetrievalConditionConfig(
        condition_id="whole_file", retriever="whole_file", format_variant="A"
    )


def test_oracle_files_covers_modified_and_created(tasks_dir):
    """A created file has no body to read, but naming its path is the same kind
    of oracle knowledge and must not be dropped."""
    assert oracle_files("T1", tasks_dir) == ["src/App.tsx", "src/hooks/useThing.ts"]


async def test_full_source_reaches_the_context(tasks_dir, repo):
    result = await WholeFileRetriever(
        _config(), task_id="T1", task_type="refactoring", tasks_dir=tasks_dir
    ).retrieve("do the thing", "", repo)

    assert "export const App = () => <div />" in result.context
    assert result.retriever_name == "whole_file"
    assert result.total_token_count > 0


async def test_absent_created_file_is_announced_not_invented(tasks_dir, repo):
    """Inventing contents for a file the task creates would be handing over a
    solution, not context."""
    result = await WholeFileRetriever(
        _config(), task_id="T1", tasks_dir=tasks_dir
    ).retrieve("spec", "", repo)

    assert result.metadata["oracle_files_absent"] == ["src/hooks/useThing.ts"]
    assert result.metadata["oracle_files_read"] == ["src/App.tsx"]
    assert "src/hooks/useThing.ts" in result.context


async def test_no_kg_and_no_llm_are_touched(tasks_dir, repo, monkeypatch):
    """Retrieval cost is zero by construction — that is what makes this the
    right comparison point for the token-cost table."""
    import src.graph.connection as connection

    def explode(*a, **k):  # pragma: no cover - only runs on regression
        raise AssertionError("whole_file must not query the graph")

    monkeypatch.setattr(connection, "run_query", explode)
    result = await WholeFileRetriever(
        _config(), task_id="T1", tasks_dir=tasks_dir
    ).retrieve("spec", "", repo)
    assert result.rounds == []


async def test_missing_modified_file_degrades_instead_of_raising(tasks_dir, tmp_path):
    """A per-candidate failure is recorded, never fatal to a run."""
    empty_repo = tmp_path / "empty"
    empty_repo.mkdir()
    result = await WholeFileRetriever(
        _config(), task_id="T1", tasks_dir=tasks_dir
    ).retrieve("spec", "", empty_repo)
    assert result.metadata["oracle_files_read"] == []
    assert len(result.metadata["oracle_files_absent"]) == 2
