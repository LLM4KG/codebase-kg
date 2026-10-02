"""Context assembler: Cypher query rows -> ContextData for the Format-A renderer.

Reads full component source from disk using the filePath fields returned by the
templates, folds KG metadata into ComponentContext fields (props/hooks/state/
contexts) rendered by format_a.jinja2, builds cross-cutting notes, and applies
the per-template token-budget truncation priority from cypher_templates.md §8.

Token counting is a word-based estimate (~1.3 tokens/word) — sufficient for the
Phase 1a pilot budget. The precise multi-tokenizer equalizer arrives in Phase 3.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from src.retrieval.models import ComponentContext, ContextData

logger = logging.getLogger(__name__)

DEFAULT_TOKEN_BUDGET = 7000
_TOKENS_PER_WORD = 1.3


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _estimate_tokens(text: str) -> int:
    return int(len(text.split()) * _TOKENS_PER_WORD)


def _clean(items: list[dict] | None, key: str = "name") -> list[dict]:
    """Drop the all-null placeholder dicts Cypher's collect() emits for empty OPTIONAL MATCHes."""
    return [d for d in (items or []) if d and d.get(key) is not None]


def _read_source(repo_root: Path, file_path: str | None) -> str | None:
    if not file_path:
        return None
    full = repo_root / file_path
    try:
        return full.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        logger.warning("Could not read source for %s (resolved: %s)", file_path, full)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Intermediate assembly structure (truncation operates on this, then materializes)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class _Assembly:
    task_spec: str
    task_type: str
    project_name: str
    anchors: list[ComponentContext] = field(default_factory=list)          # full source, never dropped
    secondary_sources: list[ComponentContext] = field(default_factory=list)  # delegated/existing hooks (source)
    neighbors: list[tuple[str, ComponentContext]] = field(default_factory=list)  # (role, cc) metadata-only
    kept_notes: list[str] = field(default_factory=list)      # routing table / caller warning — never dropped
    droppable_notes: list[str] = field(default_factory=list)  # context/handler notes

    def estimate(self) -> int:
        total = _estimate_tokens(self.task_spec)
        for cc in self.anchors + self.secondary_sources:
            total += _estimate_tokens(cc.source_code or "")
            total += _estimate_tokens(" ".join(p.get("name", "") for p in cc.props))
            total += _estimate_tokens(" ".join(h.get("name", "") for h in cc.hooks))
            total += _estimate_tokens(" ".join(s.get("name", "") for s in cc.state_variables))
            total += _estimate_tokens(" ".join(cc.contexts_consumed))
        for _role, cc in self.neighbors:
            total += _estimate_tokens(f"{cc.name} {cc.file_path}")
            # Neighbour props/state are rendered too, so they have to be counted
            # or the budget silently under-reports and truncation fires late.
            total += _estimate_tokens(" ".join(p.get("name", "") for p in cc.props))
            total += _estimate_tokens(" ".join(s.get("name", "") for s in cc.state_variables))
        for note in self.kept_notes + self.droppable_notes:
            total += _estimate_tokens(note)
        return total

    def materialize(self) -> ContextData:
        return ContextData(
            task_spec=self.task_spec,
            task_type=self.task_type,
            target_components=self.anchors + self.secondary_sources,
            neighbor_components=[
                cc.model_copy(update={"relation": role}) for role, cc in self.neighbors
            ],
            cross_cutting_notes=self.kept_notes + self.droppable_notes,
            project_name=self.project_name,
            retriever_name="kg_augmented",
        )


def _anchor_context(row: dict, repo_root: Path) -> ComponentContext:
    hooks = _clean(row.get("libraryHooks")) + _clean(row.get("customHooks"))
    state = _clean(row.get("stateVars")) + _clean(row.get("classStateVars"))
    contexts = [c["name"] for c in _clean(row.get("consumedContexts"))]
    return ComponentContext(
        name=row["componentName"],
        file_path=row["filePath"],
        source_code=_read_source(repo_root, row["filePath"]),
        component_type=row.get("componentType") or "",
        props=_clean(row.get("acceptedProps")),
        hooks=hooks,
        state_variables=state,
        contexts_consumed=contexts,
    )


def _neighbor_uid(entry: dict) -> str:
    """Key a neighbour for the props join.

    Prefer the uid the query returned; fall back to the schema's composite
    convention (`name::filePath`) so a template that does not select `uid` still
    joins rather than silently losing its props.
    """
    uid = entry.get("uid")
    if uid:
        return uid
    name, path = entry.get("name"), entry.get("filePath")
    return f"{name}::{path}" if name and path else ""


def _metadata_neighbor(entry: dict, neighbor_props: dict[str, dict] | None = None) -> ComponentContext:
    """Build a neighbour entry, enriched with its props/state when available.

    Without the props a neighbour renders as a heading plus a path — which the
    anchor's own import list already showed. P2's five kg_augmented candidates
    failed to build on a required prop (`dataTestID`) that was in the KG but not
    in the prompt; the whole-file oracle, which sees the component body, passed.
    """
    extra = (neighbor_props or {}).get(_neighbor_uid(entry), {})
    return ComponentContext(
        name=entry.get("name") or "",
        file_path=entry.get("filePath") or "",
        source_code=None,
        component_type="",
        props=_clean(extra.get("props")),
        state_variables=_clean(extra.get("stateVars")),
    )


def routing_notes(routing_rows: list[dict] | None) -> tuple[list[str], set[str]]:
    """Render the routing table as note lines, and return the paths it covers.

    Extracted from `_build_feature_addition` (WP8, 2026-09-21) so the hardened
    retriever's project-overview fallback can show the same table without duplicating
    the formatting. The lines are byte-identical to what feature_addition rendered
    before the extraction.
    """
    lines: list[str] = []
    known_paths: set[str] = set()
    if not routing_rows:
        return lines, known_paths
    lines.append("Project routing table:")
    for r in routing_rows:
        path = r.get("routePath")
        if path:
            known_paths.add(path)
        flags = []
        if r.get("isNested"):
            flags.append("nested")
        if r.get("isProtected"):
            flags.append("protected")
        if r.get("isLazy"):
            flags.append("lazy")
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        lines.append(
            f"  {path} → {r.get('targetComponent')} ({r.get('targetFile')}); "
            f"router {r.get('routerComponent')} ({r.get('routerFile')}){flag_str}"
        )
    return lines, known_paths


def _handler_note(row: dict) -> str | None:
    handlers = _clean(row.get("eventHandlers"), key="handlerName")
    if not handlers:
        return None
    parts = [f"{h.get('eventType', '?')}→{h['handlerName']}" for h in handlers]
    return f"{row['componentName']} event handlers: {', '.join(parts)}"


# ─────────────────────────────────────────────────────────────────────────────
# Per-template builders
# ─────────────────────────────────────────────────────────────────────────────

def _build_bug_fix(
    a: _Assembly,
    rows: list[dict],
    repo_root: Path,
    neighbor_props: dict[str, dict] | None = None,
) -> None:
    seen_hooks: set[str] = set()
    for row in rows:
        a.anchors.append(_anchor_context(row, repo_root))
        for parent in _clean(row.get("directParents")):
            a.neighbors.append(("parent", _metadata_neighbor(parent, neighbor_props)))
        # Hook anchors have no prop-passing parent; their blast radius is the set
        # of components calling them. Empty for component anchors.
        for consumer in _clean(row.get("usedByComponents")):
            a.neighbors.append(("used_by", _metadata_neighbor(consumer, neighbor_props)))
        for hook in _clean(row.get("delegatedHooks"), key="filePath"):
            if hook["filePath"] in seen_hooks:
                continue
            seen_hooks.add(hook["filePath"])
            a.secondary_sources.append(
                ComponentContext(
                    name=hook.get("name") or "",
                    file_path=hook["filePath"],
                    source_code=_read_source(repo_root, hook["filePath"]),
                    component_type="Custom_Hook",
                )
            )
        note = _handler_note(row)
        if note:
            a.droppable_notes.append(note)


def _build_feature_addition(
    a: _Assembly,
    rows: list[dict],
    routing_rows: list[dict],
    anchor_routes: list[str],
    repo_root: Path,
    neighbor_props: dict[str, dict] | None = None,
) -> None:
    seen_hooks: set[str] = set()
    for row in rows:
        a.anchors.append(_anchor_context(row, repo_root))
        for child in _clean(row.get("children")):
            a.neighbors.append(("child", _metadata_neighbor(child, neighbor_props)))
        # One-hop custom-hook source, as refactoring already reads. A feature often
        # lands in the hook rather than the component (a new action on a context
        # hook); with only the hook's name in the prompt the model cannot write a
        # search_replace block against a file it has never seen.
        for hook in _clean(row.get("customHooks"), key="filePath"):
            if hook["filePath"] in seen_hooks:
                continue
            seen_hooks.add(hook["filePath"])
            a.secondary_sources.append(
                ComponentContext(
                    name=hook.get("name") or "",
                    file_path=hook["filePath"],
                    source_code=_read_source(repo_root, hook["filePath"]),
                    component_type="Custom_Hook",
                )
            )
        for ctx in _clean(row.get("consumedContexts")):
            if ctx.get("providerName"):
                a.droppable_notes.append(
                    f"Context {ctx['name']} is provided by {ctx['providerName']} "
                    f"at {ctx.get('providerFile', '?')}; consumers may useContext({ctx['name']}) "
                    "without prop-drilling."
                )

    # Routing table (Query B) — kept even at high cost; the unique KG value-add here.
    lines, known_paths = routing_notes(routing_rows)
    a.kept_notes.extend(lines)
    for route in anchor_routes:
        if route not in known_paths:
            a.kept_notes.append(
                f"⚠ The spec references route '{route}' — not present in the routing table above."
            )


def _build_refactoring(
    a: _Assembly,
    rows: list[dict],
    repo_root: Path,
    caller_props: dict[str, list[str]],
    neighbor_props: dict[str, dict] | None = None,
) -> None:
    seen_hooks: set[str] = set()
    for row in rows:
        a.anchors.append(_anchor_context(row, repo_root))

        # Callers sorted by coupling (most props passed first); propsPassed comes
        # from the L3 split query, joined here on caller.uid.
        callers = _clean(row.get("callers"))
        callers.sort(key=lambda c: len(caller_props.get(c.get("uid", ""), [])), reverse=True)
        for caller in callers:
            a.neighbors.append(("caller", _metadata_neighbor(caller, neighbor_props)))
        for child in _clean(row.get("children")):
            a.neighbors.append(("child", _metadata_neighbor(child, neighbor_props)))

        for hook in _clean(row.get("customHooks"), key="filePath"):
            if hook["filePath"] in seen_hooks:
                continue
            seen_hooks.add(hook["filePath"])
            a.secondary_sources.append(
                ComponentContext(
                    name=hook.get("name") or "",
                    file_path=hook["filePath"],
                    source_code=_read_source(repo_root, hook["filePath"]),
                    component_type="Custom_Hook",
                )
            )

        note = _handler_note(row)
        if note:
            a.droppable_notes.append(note)

        # Caller blast-radius warning — high priority, never dropped.
        if callers:
            labels = []
            for c in callers:
                if not c.get("name"):
                    continue
                props = caller_props.get(c.get("uid", ""), [])
                labels.append(f"{c['name']} (props: {', '.join(props)})" if props else c["name"])
            a.kept_notes.append(
                f"⚠ Refactoring {row['componentName']}'s prop interface will require "
                f"updating {len(labels)} caller(s): {'; '.join(labels)}."
            )


# ─────────────────────────────────────────────────────────────────────────────
# Truncation (per-template reverse-priority removal; cypher_templates.md §8)
# ─────────────────────────────────────────────────────────────────────────────

def _clear_target_metadata(a: _Assembly, *, hooks_state: bool = False, props: bool = False) -> None:
    for cc in a.anchors:
        if hooks_state:
            cc.hooks = []
            cc.state_variables = []
        if props:
            cc.props = []


def _drop_neighbors_by_role(a: _Assembly, role: str) -> None:
    a.neighbors[:] = [n for n in a.neighbors if n[0] != role]


def _clear_neighbor_props(a: _Assembly) -> None:
    """Strip neighbour props/state, keeping the names.

    Sits immediately before the rung that removes the remaining neighbours
    outright, so it is only reached when the alternative is losing the section
    entirely. Deliberately not earlier: a bare name-and-path is close to
    worthless — that is the defect this whole change exists to fix — so trading
    props away to keep names is only worth doing as the last step before the
    names go too.
    """
    for _role, cc in a.neighbors:
        cc.props = []
        cc.state_variables = []


def _drop_refactoring_internal_metadata(a: _Assembly) -> None:
    _clear_target_metadata(a, hooks_state=True)
    a.droppable_notes.clear()


def _removal_steps(task_type: str) -> list[Callable[[_Assembly], None]]:
    """Reverse-priority removal steps (lowest priority first) per cypher_templates.md §8."""
    if task_type == "bug_fix":
        return [
            lambda a: _drop_neighbors_by_role(a, "parent"),         # direct parents
            lambda a: a.droppable_notes.clear(),                   # event handlers
            _clear_neighbor_props,                                 # neighbour props/state
            # `used_by` outranks event handlers: for a Custom_Hook anchor it *is*
            # the blast radius, and a hook has no prop-passing parent to fall back
            # on. Clearing all neighbours at step 0 dropped it first.
            lambda a: _drop_neighbors_by_role(a, "used_by"),        # hook consumers
            lambda a: _clear_target_metadata(a, hooks_state=True),  # state + hooks
            lambda a: _clear_target_metadata(a, props=True),        # accepted props
            lambda a: a.secondary_sources.clear(),                 # delegated hook source
        ]
    if task_type == "feature_addition":
        return [
            lambda a: a.droppable_notes.clear(),                   # context notes (routing kept)
            _clear_neighbor_props,                                 # neighbour props/state
            lambda a: a.neighbors.clear(),                         # children metadata
            lambda a: a.secondary_sources.clear(),                 # custom-hook source
        ]
    if task_type == "refactoring":
        return [
            lambda a: _drop_neighbors_by_role(a, "child"),         # children (callers kept)
            _drop_refactoring_internal_metadata,                   # internal hooks/state + handler notes
            lambda a: a.secondary_sources.clear(),                 # existing hook source
            _clear_neighbor_props,                                 # neighbour props/state
            lambda a: a.neighbors.clear(),                         # caller metadata (⚠ note stays)
        ]
    return []


def _truncate(a: _Assembly, budget: int) -> None:
    for step in _removal_steps(a.task_type):
        if a.estimate() <= budget:
            return
        step(a)


# ─────────────────────────────────────────────────────────────────────────────
# Public entrypoint
# ─────────────────────────────────────────────────────────────────────────────

def assemble_context(
    *,
    task_spec: str,
    task_type: str,
    rows: list[dict],
    repo_root: str | Path,
    project_name: str = "",
    routing_rows: list[dict] | None = None,
    anchor_routes: list[str] | None = None,
    caller_props: dict[str, list[str]] | None = None,
    neighbor_props: dict[str, dict] | None = None,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
) -> ContextData:
    """Turn dispatched Cypher query rows into a truncated ContextData for rendering.

    `neighbor_props` maps a neighbour's uid to its `{props, stateVars}`, from the
    `neighbor_props.cypher` companion query. Optional: absent, neighbours render
    as name and path exactly as before.
    """
    repo = Path(repo_root)
    a = _Assembly(task_spec=task_spec, task_type=task_type, project_name=project_name)
    neighbors = neighbor_props or {}

    if task_type == "bug_fix":
        _build_bug_fix(a, rows, repo, neighbors)
    elif task_type == "feature_addition":
        _build_feature_addition(a, rows, routing_rows or [], anchor_routes or [], repo, neighbors)
    elif task_type == "refactoring":
        _build_refactoring(a, rows, repo, caller_props or {}, neighbors)
    else:
        # Unknown type — treat rows as plain anchors.
        for row in rows:
            a.anchors.append(_anchor_context(row, repo))

    _truncate(a, token_budget)
    return a.materialize()


def assemble_overview(
    *,
    task_spec: str,
    task_type: str,
    rows: list[dict],
    project_name: str = "",
    routing_rows: list[dict] | None = None,
    anchor_routes: list[str] | None = None,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
) -> ContextData:
    """Assemble the last-resort project overview from `project_overview.cypher` rows.

    Reached only under `anchor_resolution = "hardened"`, and only when not one anchor
    the classifier produced resolved to a node — the case where the anchor-scoped
    templates would otherwise return zero rows and render an empty context (WP8).

    Metadata only: names, paths, props, hooks and state, never source. Components are
    dropped from the tail until the estimate fits `token_budget`, so the fallback is
    bounded by construction rather than by the truncation ladder, whose priorities are
    written for anchor-scoped context and do not apply here.

    For a feature_addition the routing table is carried through as well: it is
    project-wide by construction, so it is the one piece of anchor-independent context
    the KG can always offer.

    Kept separate from `assemble_context` on purpose: it must not be able to change what
    the strict path assembles.
    """
    note = (
        "⚠ No anchor from the task statement resolved to a component or hook in the "
        "knowledge graph. The section below is a project-wide overview of the largest "
        "components, not context scoped to the task — treat it as orientation only."
    )
    entries = [
        ComponentContext(
            name=row.get("componentName") or "",
            file_path=row.get("filePath") or "",
            source_code=None,
            component_type=row.get("componentType") or "",
            props=[{"name": n} for n in (row.get("propNames") or []) if n],
            hooks=[{"name": n} for n in (row.get("hookNames") or []) if n],
            state_variables=[{"name": n} for n in (row.get("stateNames") or []) if n],
            relation="project_overview",
        )
        for row in rows
        if row.get("componentName")
    ]

    route_lines, known_paths = routing_notes(routing_rows)
    for route in anchor_routes or []:
        if route not in known_paths:
            route_lines.append(
                f"⚠ The spec references route '{route}' — not present in the routing table above."
            )

    def estimate(kept: list[ComponentContext]) -> int:
        total = _estimate_tokens(task_spec) + _estimate_tokens(note)
        total += sum(_estimate_tokens(line) for line in route_lines)
        for cc in kept:
            total += _estimate_tokens(f"{cc.name} {cc.file_path}")
            for items in (cc.props, cc.hooks, cc.state_variables):
                total += _estimate_tokens(" ".join(i.get("name", "") for i in items))
        return total

    while entries and estimate(entries) > token_budget:
        entries.pop()

    return ContextData(
        task_spec=task_spec,
        task_type=task_type,
        target_components=[],
        neighbor_components=entries,
        cross_cutting_notes=[note] + route_lines,
        project_name=project_name,
        retriever_name="kg_augmented",
    )
