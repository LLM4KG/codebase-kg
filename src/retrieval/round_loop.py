"""Round-loop control flow for retrieval execution.

Single-round (max_rounds=1) is the primary experiment path.
Iterative (max_rounds>1) is scaffolded here for Phase 6.

call_purpose threading contract for Phase 3/Phase 6 implementers:
  - Classifier calls         → call_purpose="classifier"
  - Anchor extractor calls   → call_purpose="anchor_extractor"
  - Reformulator calls       → call_purpose="reformulator"
  - Generator calls          → call_purpose="generator" (downstream, not in this module)
"""

from __future__ import annotations

import logging
from pathlib import Path

from src.retrieval.base import Retriever
from src.retrieval.models import RetrievalResult

logger = logging.getLogger(__name__)

STOP_TOKENS = frozenset({"STOP", "[STOP]", "<STOP>"})


def is_stop_signal(query: str | None) -> bool:
    """Check if the retriever's next_query indicates stopping."""
    if query is None:
        return True
    return query.strip().upper() in STOP_TOKENS


async def execute_retrieval(
    retriever: Retriever,
    spec: str,
    project_id: str,
    repo_root: str | Path,
    max_rounds: int = 1,
) -> RetrievalResult:
    """Execute the retrieval loop.

    For single-round (max_rounds=1):
      1. Call retriever.retrieve() once
      2. Return result with one RoundRecord

    For iterative (max_rounds>1, Phase 6):
      1. Call retriever.retrieve() for round 1
      2. Call retriever.next_query() to get follow-up query
      3. If next_query returns None or a STOP token, stop
      4. Otherwise, execute follow-up and append to round history
      5. Repeat until max_rounds or STOP
    """
    result = await retriever.retrieve(
        spec=spec,
        project_id=project_id,
        repo_root=repo_root,
        max_rounds=max_rounds,
    )

    if max_rounds <= 1:
        return result

    for round_num in range(2, max_rounds + 1):
        try:
            next_q = retriever.next_query(result.rounds)
        except NotImplementedError:
            logger.debug(
                "%s does not support iterative retrieval, stopping after round 1",
                retriever.__class__.__name__,
            )
            break

        if is_stop_signal(next_q):
            logger.debug("Stop signal received after round %d", round_num - 1)
            break

        result = await retriever.retrieve(
            spec=next_q,
            project_id=project_id,
            repo_root=repo_root,
            max_rounds=1,
        )

    return result
