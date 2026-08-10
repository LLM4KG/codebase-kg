"""Whole-file oracle retriever — the contentful non-KG baseline.

Condition 2 of the six-condition ladder (`phase2_design_summary.md`): the full
source of every file the reference patch edits, handed over directly. It is the
only condition with **oracle localisation** — it is told where to look — which
is the point. Everything else, KG-augmented included, has to find that out for
itself, so whole-file bounds how much of any advantage is localisation rather
than structure.

**Why it exists now rather than in Phase 3.** The 2026-07-23 pilot ran only
`floor` and `kg_augmented`, and all 15 floor candidates died at the apply stage.
Reading the prompts shows why: floor's is 436 tokens of system + spec +
instruction with no source code at all, so it fabricates both paths and file
contents and cannot match anything. That is the ablation working as designed,
but it leaves the comparison with no non-KG arm that ever reaches build or test
— and no output format fixes that, because the problem is the absence of
information, not the shape of the answer. Whole-file is the cheapest arm that
does reach them.

Deliberately no LLM and no KG: `files_modified` comes from the frozen task YAML.
Retrieval cost is zero by construction, which is exactly what makes it the right
comparison point for the token-cost table.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from src.retrieval.assembler import _estimate_tokens, _read_source
from src.retrieval.base import Retriever
from src.retrieval.config import RetrievalConditionConfig
from src.retrieval.models import ComponentContext, ContextData, RetrievalResult
from src.retrieval.renderer import ContextRenderer

logger = logging.getLogger(__name__)

TASKS_DIR = Path("tasks/pilot")


def oracle_files(task_id: str, tasks_dir: Path = TASKS_DIR) -> list[str]:
    """The files the reference patch touches — the oracle localisation signal.

    `files_created` is included alongside `files_modified`: a created file has no
    source to read, but naming it tells the generator the path the reference
    solution chose, which is the same kind of oracle knowledge.
    """
    with open(tasks_dir / f"{task_id}.yaml", encoding="utf-8") as f:
        spec = yaml.safe_load(f)
    return list(spec.get("files_modified") or []) + list(spec.get("files_created") or [])


class WholeFileRetriever(Retriever):
    """Oracle whole-file context. No LLM call, no KG query, no token budget."""

    def __init__(
        self,
        config: RetrievalConditionConfig,
        *,
        task_id: str,
        task_type: str = "",
        project_name: str = "",
        tasks_dir: Path = TASKS_DIR,
    ) -> None:
        super().__init__(config)
        # `Retriever.retrieve()` takes no task argument, so the task identity
        # arrives at construction — the same shape KGAugmentedRetriever uses for
        # `project_name`.
        self.task_id = task_id
        self.task_type = task_type
        self.project_name = project_name
        self.tasks_dir = tasks_dir

    async def retrieve(
        self,
        spec: str,
        project_id: str,
        repo_root: str | Path,
        max_rounds: int = 1,
    ) -> RetrievalResult:
        repo = Path(repo_root)
        components: list[ComponentContext] = []
        missing: list[str] = []

        for rel_path in oracle_files(self.task_id, self.tasks_dir):
            source = _read_source(repo, rel_path)
            if source is None:
                # A file the reference patch creates. Named without a body — the
                # path is the signal; inventing contents would be a solution, not
                # context.
                missing.append(rel_path)
                continue
            components.append(
                ComponentContext(
                    name=Path(rel_path).stem,
                    file_path=rel_path,
                    source_code=source,
                    component_type="file",
                )
            )

        notes = [
            f"This task creates a new file: `{p}`. It does not exist yet."
            for p in missing
        ]

        context_data = ContextData(
            task_spec=spec,
            task_type=self.task_type,
            target_components=components,
            neighbor_components=[],
            cross_cutting_notes=notes,
            project_name=self.project_name,
        )
        context = ContextRenderer().render(self.config.format_variant, context_data)

        return RetrievalResult(
            context=context,
            rounds=[],
            retriever_name="whole_file",
            condition_id=self.config.condition_id,
            total_token_count=_estimate_tokens(context),
            metadata={
                "oracle_files_read": [c.file_path for c in components],
                "oracle_files_absent": missing,
            },
        )
