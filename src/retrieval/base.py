"""Abstract Retriever base class for all retrieval conditions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from src.retrieval.config import RetrievalConditionConfig
from src.retrieval.models import RetrievalResult, RoundRecord


class Retriever(ABC):
    """Base class for all retrieval conditions."""

    def __init__(self, config: RetrievalConditionConfig) -> None:
        self.config = config

    @abstractmethod
    async def retrieve(
        self,
        spec: str,
        project_id: str,
        repo_root: str | Path,
        max_rounds: int = 1,
    ) -> RetrievalResult:
        """Retrieve context for a code generation task.

        Args:
            spec: Natural language task specification (1-3 sentences).
            project_id: Project identifier for KG scoping.
            repo_root: Path to the project repository root.
            max_rounds: Maximum retrieval rounds (1 = single-round, >1 = iterative).

        Returns:
            RetrievalResult containing context string and round history.
        """
        ...

    def next_query(self, round_history: list[RoundRecord]) -> str | None:
        """For iterative mode: examine previous results and formulate a follow-up query.

        Returns None to signal stopping. Overridden in Phase 6 for iterative conditions.
        Raises NotImplementedError in single-round retrievers.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support iterative retrieval"
        )
