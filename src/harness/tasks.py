"""Read-only loader over tasks/pilot/*.yaml. Does not touch Work item 1 assets."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel


class PilotTask(BaseModel):
    task_id: str
    project_id: str
    git_commit: str
    task_type: str
    test_files: list[str]


def load_pilot_task(task_id: str, tasks_dir: Path = Path("tasks/pilot")) -> PilotTask:
    """Load a pilot task YAML by id. Only models the fields the harness needs."""
    path = tasks_dir / f"{task_id}.yaml"
    with open(path) as f:
        data = yaml.safe_load(f)
    return PilotTask(
        task_id=data["task_id"],
        project_id=data["project_id"],
        git_commit=data["git_commit"],
        task_type=data["task_type"],
        test_files=data["test_files"],
    )
