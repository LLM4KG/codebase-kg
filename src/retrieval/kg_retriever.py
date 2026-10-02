"""KG-augmented retriever (Format A) for the `kg_augmented` condition.

Pipeline: classify the task + extract anchors -> dispatch the matching Cypher
template(s) against Memgraph -> assemble a ContextData from the rows -> render the
Format-A prompt block. Ends at a RetrievalResult; the generator call + diff
extraction live in Work item 4.
"""

from __future__ import annotations

import asyncio
import logging
from functools import lru_cache
from pathlib import Path

from src.graph.connection import run_query
from src.llm.prompt_loader import render_prompt
from src.retrieval.anchor_resolver import (
    AnchorResolution,
    known_routes,
    resolve_anchors,
    resolved_names,
)
from src.retrieval.assembler import assemble_context, assemble_overview
from src.retrieval.base import Retriever
from src.retrieval.classifier import ClassifierResult, classify_task
from src.retrieval.config import RetrievalConditionConfig
from src.retrieval.models import RetrievalResult, RoundRecord
from src.retrieval.renderer import ContextRenderer

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"
_TOKENS_PER_WORD = 1.3

# task_type -> the primary template file executed for it.
_TEMPLATE_BY_TYPE = {
    "bug_fix": "bug_fix.cypher",
    "feature_addition": "feature_addition_a.cypher",
    "refactoring": "refactoring.cypher",
}
_ROUTING_TEMPLATE = "feature_addition_b.cypher"
_REFACTORING_CALLER_PROPS_TEMPLATE = "refactoring_caller_props.cypher"
_NEIGHBOR_PROPS_TEMPLATE = "neighbor_props.cypher"
_ANCHOR_CANDIDATES_TEMPLATE = "anchor_candidates.cypher"
_PROJECT_OVERVIEW_TEMPLATE = "project_overview.cypher"

# How anchor names from the classifier are matched against the graph. WP8, 2026-09-21.
#   "strict"   — today's behaviour and the one WP5 measured: the raw names go straight
#                into `$anchorNames`, matched by exact, case-sensitive equality. A name
#                that does not exist matches nothing and the context comes out empty.
#   "hardened" — resolve first (exact -> case-insensitive -> fuzzy), record every
#                resolution in the metadata, and when nothing resolves at all fall back
#                to a bounded project overview instead of rendering nothing.
# Set per condition via `[retriever_params] anchor_resolution`. The default must stay
# "strict": conditions/base/kg_augmented.toml is the published arm.
ANCHOR_RESOLUTION_MODES = ("strict", "hardened")
DEFAULT_ANCHOR_RESOLUTION = "strict"
# Rows of `project_overview.cypher` to request; the token budget then trims further.
# 40 covers every component of both pilot repos (14 and 44) and costs 198 tokens for
# react-shopping-cart and ~590 for TakeNote — metadata only, so an order of magnitude
# under the 7,000-token budget, and comparable to a real anchor-scoped context.
OVERVIEW_LIMIT = 40

# Row fields holding neighbour components, across all three primary templates.
# Their props are fetched by the companion query and joined on uid.
_NEIGHBOR_FIELDS = ("children", "callers", "directParents", "usedByComponents")


@lru_cache(maxsize=None)
def load_template(name: str) -> str:
    """Read a raw .cypher template by filename (cached)."""
    return (TEMPLATES_DIR / name).read_text(encoding="utf-8")


def _estimate_tokens(text: str) -> int:
    return int(len(text.split()) * _TOKENS_PER_WORD)


def build_generation_prompt(
    spec: str,
    context_block: str,
    instruction_template: str = "generation/instruction_unified_diff.jinja2",
) -> str:
    """Assemble the shared generation prompt: [system][spec][context][instruction].

    The context block is empty for the floor condition. No generator call is made
    here — this only constructs the prompt string for Work item 4 to send.

    Only the instruction section varies with the output format; the system prompt,
    the spec and the retrieved context are identical across formats, so a
    format comparison differs in exactly one block of text.
    """
    system = render_prompt("generation/system.jinja2")
    instruction = render_prompt(instruction_template)
    parts = [system.strip(), f"## Task\n\n{spec.strip()}"]
    if context_block.strip():
        parts.append(context_block.strip())
    parts.append(instruction.strip())
    return "\n\n".join(parts) + "\n"


class KGAugmentedRetriever(Retriever):
    """Classifier + Cypher-template + assembler retriever rendering Format A."""

    def __init__(
        self,
        config: RetrievalConditionConfig,
        *,
        model: str,
        run_id: str,
        project_name: str = "",
        token_budget: int = 7000,
        log_dir: Path | None = None,
    ) -> None:
        super().__init__(config)
        self.model = model
        self.run_id = run_id
        self.project_name = project_name
        self.token_budget = token_budget
        self.log_dir = log_dir
        self._renderer = ContextRenderer()
        mode = config.retriever_params.get("anchor_resolution", DEFAULT_ANCHOR_RESOLUTION)
        if mode not in ANCHOR_RESOLUTION_MODES:
            raise ValueError(
                f"condition {config.condition_id!r} has anchor_resolution={mode!r} — "
                f"expected one of {', '.join(ANCHOR_RESOLUTION_MODES)}"
            )
        self.anchor_resolution = mode

    async def _run_query(self, name: str, params: dict) -> list[dict]:
        """Execute a template off the event loop (the Bolt driver is synchronous)."""
        query = load_template(name)
        return await asyncio.to_thread(run_query, query, params)

    @staticmethod
    def _neighbor_uids(rows: list[dict]) -> list[str]:
        """Collect every neighbour uid the primary query returned, de-duplicated.

        Falls back to the schema's `name::filePath` composite for templates whose
        collect() omits uid, matching `_neighbor_uid()` in the assembler.
        """
        uids: list[str] = []
        seen: set[str] = set()
        for row in rows:
            for field in _NEIGHBOR_FIELDS:
                for entry in row.get(field) or []:
                    if not isinstance(entry, dict):
                        continue
                    uid = entry.get("uid")
                    if not uid and entry.get("name") and entry.get("filePath"):
                        uid = f"{entry['name']}::{entry['filePath']}"
                    if uid and uid not in seen:
                        seen.add(uid)
                        uids.append(uid)
        return uids

    async def _fetch_neighbor_props(
        self, rows: list[dict], project_id: str
    ) -> dict[str, dict]:
        """Fetch props/state for the neighbours, keyed by uid.

        Runs for every task type: all three primary templates return neighbours
        as name and path only, which renders as a heading the import list already
        showed. Skipped entirely when there are no neighbours.
        """
        uids = self._neighbor_uids(rows)
        if not uids:
            return {}
        prop_rows = await self._run_query(
            _NEIGHBOR_PROPS_TEMPLATE, {"projectId": project_id, "neighborUids": uids}
        )
        return {
            r["uid"]: {"props": r.get("props") or [], "stateVars": r.get("stateVars") or []}
            for r in prop_rows
            if r.get("uid")
        }

    async def _dispatch(
        self, classification: ClassifierResult, project_id: str, repo_root: str | Path
    ):
        params = {
            "projectId": project_id,
            "anchorNames": classification.anchor_names,
            "anchorRoutes": classification.anchor_routes,
        }
        task_type = classification.task_type
        template_name = _TEMPLATE_BY_TYPE[task_type]
        rows = await self._run_query(template_name, params)

        routing_rows: list[dict] = []
        caller_props: dict[str, list[str]] = {}
        if task_type == "feature_addition":
            routing_rows = await self._run_query(_ROUTING_TEMPLATE, params)
        elif task_type == "refactoring":
            # L3 split: per-caller props fetched separately and joined on caller.uid.
            prop_rows = await self._run_query(_REFACTORING_CALLER_PROPS_TEMPLATE, params)
            caller_props = {
                r["callerUid"]: r.get("propsPassed") or []
                for r in prop_rows
                if r.get("callerUid")
            }

        neighbor_props = await self._fetch_neighbor_props(rows, project_id)

        context_data = assemble_context(
            task_spec="",  # filled by caller; assembler only uses it for token accounting
            task_type=task_type,
            rows=rows,
            repo_root=repo_root,
            project_name=self.project_name,
            routing_rows=routing_rows,
            anchor_routes=classification.anchor_routes,
            caller_props=caller_props,
            neighbor_props=neighbor_props,
            token_budget=self.token_budget,
        )
        return context_data

    async def _resolve(
        self, classification: ClassifierResult, project_id: str, spec: str
    ) -> list[AnchorResolution]:
        """Resolve the classifier's anchor names against the project's own nodes."""
        rows = await self._run_query(_ANCHOR_CANDIDATES_TEMPLATE, {"projectId": project_id})
        return resolve_anchors(classification.anchor_names, rows, spec)

    async def _check_routes(
        self, classification: ClassifierResult, project_id: str
    ) -> tuple[list[str], list[str]]:
        """Split the classifier's routes into those the graph has and those it does not.

        Runs only under "hardened", and only when the classifier extracted a route at
        all — 2 of the 60 WP5 calls did, and one of those two named a route TakeNote
        does not have. The routing table is project-wide, so this is the same query
        `_dispatch` runs for a feature_addition; running it here rather than reaching
        into `_dispatch` keeps that method's signature fixed for
        `scripts/wp9_retrieval_timing.py`.
        """
        rows = await self._run_query(
            _ROUTING_TEMPLATE,
            {
                "projectId": project_id,
                "anchorNames": classification.anchor_names,
                "anchorRoutes": classification.anchor_routes,
            },
        )
        paths = [r.get("routePath") for r in rows if r.get("routePath")]
        return known_routes(classification.anchor_routes, paths)

    async def _overview(self, task_type: str, project_id: str, anchor_routes: list[str]):
        """Bounded project-wide context, for the case where no anchor resolved.

        The anchor-scoped templates would return zero rows here and Format A would
        render its headers with nothing under them — the KG condition silently becomes
        the floor condition (WP8). This returns something instead, capped by
        OVERVIEW_LIMIT rows and then by the token budget, and always carrying the
        warning note that says the context is not task-scoped.
        """
        rows = await self._run_query(
            _PROJECT_OVERVIEW_TEMPLATE, {"projectId": project_id, "overviewLimit": OVERVIEW_LIMIT}
        )
        routing_rows: list[dict] = []
        if task_type == "feature_addition":
            routing_rows = await self._run_query(
                _ROUTING_TEMPLATE,
                {"projectId": project_id, "anchorNames": [], "anchorRoutes": anchor_routes},
            )
        return assemble_overview(
            task_spec="",  # filled by the caller, as _dispatch does
            task_type=task_type,
            rows=rows,
            project_name=self.project_name,
            routing_rows=routing_rows,
            anchor_routes=anchor_routes,
            token_budget=self.token_budget,
        )

    async def retrieve(
        self,
        spec: str,
        project_id: str,
        repo_root: str | Path,
        max_rounds: int = 1,
    ) -> RetrievalResult:
        classification = await classify_task(
            spec,
            model=self.model,
            run_id=self.run_id,
            condition_id=self.config.condition_id,
            log_dir=self.log_dir,
        )
        return await self.retrieve_classified(classification, spec, project_id, repo_root)

    async def retrieve_classified(
        self,
        classification: ClassifierResult,
        spec: str,
        project_id: str,
        repo_root: str | Path,
    ) -> RetrievalResult:
        """Everything `retrieve` does after the classifier call, on a given classification.

        Split out (WP8, 2026-09-21) so an already-logged or a deliberately corrupted
        classification can be replayed without an LLM call — `scripts/wp8_anchor_robustness.py`
        feeds misspelled, wrong and empty anchors through exactly this path.
        `retrieve` is classify + this, so the two cannot drift.
        """
        resolutions: list[AnchorResolution] = []
        unknown_routes: list[str] = []
        anchor_fallback = False
        dispatched = classification
        if self.anchor_resolution == "hardened":
            resolutions = await self._resolve(classification, project_id, spec)
            if classification.anchor_routes:
                _, unknown_routes = await self._check_routes(classification, project_id)
            names = resolved_names(resolutions)
            if names:
                dispatched = classification.model_copy(update={"anchor_names": names})
            else:
                anchor_fallback = True
                logger.warning(
                    "%s: no anchor of %s resolved to a node in project %s — "
                    "falling back to a bounded project overview",
                    self.config.condition_id,
                    classification.anchor_names or "[]",
                    project_id,
                )

        if anchor_fallback:
            context_data = await self._overview(
                classification.task_type, project_id, classification.anchor_routes
            )
        else:
            context_data = await self._dispatch(dispatched, project_id, repo_root)
        context_data.task_spec = spec

        rendered = self._renderer.render(self.config.format_variant, context_data)
        token_count = _estimate_tokens(rendered)

        retrieved_files = [
            cc.file_path
            for cc in (context_data.target_components + context_data.neighbor_components)
            if cc.file_path
        ]

        round_record = RoundRecord(
            round_number=1,
            query=classification.task_type,
            retrieved_files=retrieved_files,
            context_snippet=rendered[:500],
            token_count=token_count,
        )

        # Under "strict" the metadata is exactly what WP5 wrote — the regression guard.
        # The resolution fields exist only on the hardened arm, which is opt-in.
        metadata: dict = {
            "task_type": classification.task_type,
            "anchor_names": classification.anchor_names,
            "anchor_routes": classification.anchor_routes,
        }
        if self.anchor_resolution != DEFAULT_ANCHOR_RESOLUTION:
            metadata.update(
                {
                    "anchor_resolution": self.anchor_resolution,
                    "anchor_names_dispatched": dispatched.anchor_names,
                    "anchor_resolutions": [r.as_dict() for r in resolutions],
                    "anchor_routes_unknown": unknown_routes,
                    # True when not one anchor resolved, so the context below is the
                    # bounded project overview and NOT scoped to the task. Recorded
                    # rather than left to be inferred from a token count.
                    "anchor_fallback": anchor_fallback,
                }
            )

        return RetrievalResult(
            context=rendered,
            rounds=[round_record],
            retriever_name="kg_augmented",
            condition_id=self.config.condition_id,
            total_token_count=token_count,
            metadata=metadata,
        )
