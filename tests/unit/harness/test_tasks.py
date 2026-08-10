"""Tests for the read-only pilot task loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.harness.tasks import PilotTask, load_pilot_task


def test_load_real_p1_task():
    task = load_pilot_task("P1")
    assert isinstance(task, PilotTask)
    assert task.task_id == "P1"
    assert task.project_id == "react-shopping-cart"
    assert task.git_commit == "9fa56244d0f0c0d363cab744a3305c50eabc08cb"
    assert task.task_type == "bug_fix"
    assert task.test_files == [
        "src/contexts/cart-context/__tests__/P1_decrease_removes_product.test.tsx"
    ]


def test_missing_task_raises_file_not_found():
    with pytest.raises(FileNotFoundError):
        load_pilot_task("P999")


def test_custom_tasks_dir(tmp_path: Path):
    (tmp_path / "PX.yaml").write_text(
        "task_id: PX\n"
        "project_id: takenote\n"
        "git_commit: abc123\n"
        "task_type: feature_addition\n"
        "test_files:\n"
        "  - tests/unit/PX.test.ts\n"
    )
    task = load_pilot_task("PX", tasks_dir=tmp_path)
    assert task.project_id == "takenote"
    assert task.test_files == ["tests/unit/PX.test.ts"]
