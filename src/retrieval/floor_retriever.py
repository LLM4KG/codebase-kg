"""Floor retriever: the no-context baseline condition.

Returns an empty context block — the generator sees only the task spec. This is
the lower bound the KG-augmented condition is measured against in the WI4 pilot.
"""

from __future__ import annotations

from pathlib import Path

from src.retrieval.base import Retriever
from src.retrieval.models import RetrievalResult


class FloorRetriever(Retriever):
    """No retrieval — empty context. No LLM or KG calls."""

    async def retrieve(
        self,
        spec: str,
        project_id: str,
        repo_root: str | Path,
        max_rounds: int = 1,
    ) -> RetrievalResult:
        return RetrievalResult(
            context="",
            rounds=[],
            retriever_name="floor",
            condition_id=self.config.condition_id,
            total_token_count=0,
        )
