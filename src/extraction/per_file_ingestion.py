"""Stage 3: Per-file node and within-file edge creation from LLM results."""

from __future__ import annotations

import logging
import re

from src.graph import ingestion
from src.extraction.cross_file import resolve_to_manifest_file

logger = logging.getLogger(__name__)


def is_custom_hook_name(name: str) -> bool:
    """Check if name follows the useXxx custom hook convention."""
    return len(name) >= 4 and name.startswith("use") and name[3].isupper()


def recategorise_hook(
    hook: dict,
    file_path: str,
    file_manifest: list[str],
    aliases: dict[str, str] | None = None,
    base_url: str = "",
) -> str:
    """Correct a hook's library/custom category using project import config.

    `function_component.jinja2` defines "custom" as *imported via a relative path*,
    so a project using tsconfig `baseUrl` (react-shopping-cart: `import { useCart }
    from 'contexts/cart-context'`) has its own hooks labelled "library" — producing
    orphan `Library_Hook` nodes whose `source` matches no `Library`.

    Fixed here rather than in the prompt on purpose. The LLM cache key excludes
    template contents, so editing the prompt would silently return stale cached
    responses; and `baseUrl` is project configuration the model cannot know anyway.
    A hook whose source resolves to a file in this project is a custom hook,
    whatever the model called it.
    """
    category = hook.get("category")
    source = hook.get("source", "")

    if category != "library" or not source or source == "local":
        return category

    resolved = resolve_to_manifest_file(
        source, file_path, file_manifest, aliases, base_url
    )
    if resolved is None:
        return category

    logger.debug(
        "Re-categorising hook '%s' from library to custom: source '%s' resolves to %s",
        hook.get("name"), source, resolved,
    )
    return "custom"


def check_is_literal(default_value: str) -> bool:
    """Heuristic: is the default value a JavaScript literal?"""
    if not default_value:
        return False
    trimmed = default_value.strip()
    literal_patterns = [
        r"^-?\d+(\.\d+)?$",        # numeric
        r"^'[^']*'$",               # single-quoted string
        r'^"[^"]*"$',               # double-quoted string
        r"^(true|false|null|undefined)$",  # boolean/null
        r"^\[\]$",                   # empty array
        r"^\{\}$",                   # empty object
    ]
    return any(re.match(pat, trimmed) for pat in literal_patterns)


def ingest_file_results(
    file_path: str,
    llm_results: dict,
    file_manifest: list[str],
    aliases: dict[str, str] | None = None,
    base_url: str = "",
) -> None:
    """
    Ingest all LLM extraction results for a single file into the graph.

    Order matters: component nodes first, then relationships.
    """
    # ── Phase 1: Create component/hook nodes ──
    _ingest_function_components(
        file_path, llm_results, file_manifest, aliases=aliases, base_url=base_url
    )
    _ingest_custom_hooks(file_path, llm_results)
    _ingest_class_components(file_path, llm_results)

    # ── Phase 2: Create other nodes + within-file edges ──
    _ingest_props_and_handlers(file_path, llm_results)
    _ingest_function_state(file_path, llm_results)
    _ingest_class_state(file_path, llm_results)
    _ingest_contexts(file_path, llm_results)


def _ingest_function_components(
    file_path: str,
    llm_results: dict,
    file_manifest: list[str],
    aliases: dict[str, str] | None = None,
    base_url: str = "",
) -> None:
    """Create Function_Component and Custom_Hook nodes + hook usage edges."""
    fc_data = llm_results.get("function_components", {})
    components = fc_data.get("components", [])

    for comp in components:
        name = comp.get("name", "")
        if not name:
            continue

        if is_custom_hook_name(name):
            # This is a Custom_Hook, not a Function_Component
            ingestion.ingest_custom_hook_as_node(comp, file_path)
            # Hook usage edges for custom hooks are handled in Stage 4
        else:
            ingestion.ingest_function_component(comp, file_path)

            # Create hook usage edges.
            #
            # `hookDetails` carries one entry per *call site*, so a component
            # calling useState three times yields three entries. One pass folds
            # them into one entry per hook plus a call-site tally: dicts preserve
            # insertion order, so the first occurrence wins and source order is
            # kept, exactly as the previous seen_hooks set did.
            comp_uid = f"{name}::{file_path}"
            unique_hooks: dict[str, dict] = {}
            hook_counts: dict[str, int] = {}

            for hook in comp.get("hookDetails", []):
                # Keyed on name::source — the same hook name from two different
                # packages is two distinct Library_Hook nodes.
                hook_key = f"{hook['name']}::{hook.get('source', '')}"
                unique_hooks.setdefault(hook_key, hook)
                hook_counts[hook_key] = hook_counts.get(hook_key, 0) + 1

            for hook_key, hook in unique_hooks.items():
                category = recategorise_hook(
                    hook, file_path, file_manifest, aliases, base_url
                )

                if category == "library":
                    # MERGE_LIBRARY_HOOK creates the node, so there is no
                    # ordering constraint here.
                    ingestion.ingest_library_hook(
                        hook, comp_uid, hook_counts[hook_key]
                    )
                # category == "custom" is deliberately NOT handled here.
                # MERGE_FC_USES_CUSTOM_HOOK matches both endpoints, and files are
                # ingested in path order: src/components/Cart/Cart.tsx is processed
                # long before src/contexts/cart-context/useCart.ts exists as a node,
                # so the edge was a silent no-op. Deferred to Stage 4, where the
                # full node inventory is available — the same reason USES_COMPONENT
                # lives there.


def _ingest_custom_hooks(file_path: str, llm_results: dict) -> None:
    """Create Custom_Hook nodes from the dedicated hook-definition prompt.

    Runs after `_ingest_function_components`, which also routes `useXxx`-named
    entries to `ingest_custom_hook_as_node`. Both paths MERGE on the same uid, so
    the overlap is idempotent — and this one runs second so its `exportType` wins,
    the dedicated prompt being the better authority on how a hook is exported.
    """
    hook_data = llm_results.get("custom_hooks", {})

    for hook in hook_data.get("customHooks", []):
        name = hook.get("name", "")
        if not name:
            continue
        # The prompt is instructed to return only use[A-Z] names; enforce it here
        # so a stray component can never land in the graph as a hook.
        if not is_custom_hook_name(name):
            logger.warning(
                "Skipping '%s' from custom_hooks in %s: not a useXxx name",
                name, file_path,
            )
            continue
        ingestion.ingest_custom_hook_as_node(hook, file_path)


def _ingest_class_components(file_path: str, llm_results: dict) -> None:
    """Create Class_Component nodes."""
    cc_data = llm_results.get("class_components", {})
    components = cc_data.get("classComponents", [])

    for comp in components:
        name = comp.get("name", "")
        if not name:
            continue
        ingestion.ingest_class_component(comp, file_path)


def _ingest_props_and_handlers(file_path: str, llm_results: dict) -> None:
    """Create Prop and EventHandler nodes + ACCEPTS_PROP, HAS_HANDLER edges."""
    ph_data = llm_results.get("props_and_handlers", {})

    for prop in ph_data.get("props", []):
        if prop.get("name") and prop.get("componentName"):
            ingestion.ingest_prop(prop, file_path)

    seen_handlers: set[str] = set()
    for handler in ph_data.get("eventHandlers", []):
        if handler.get("name") and handler.get("componentName"):
            eh_uid = f"{handler['name']}::{handler['componentName']}::{file_path}"

            # Handle inline handler uid collisions
            if eh_uid in seen_handlers and handler.get("isInline"):
                counter = 2
                while f"{handler['name']}_{counter}::{handler['componentName']}::{file_path}" in seen_handlers:
                    counter += 1
                handler = {**handler, "name": f"{handler['name']}_{counter}"}
                eh_uid = f"{handler['name']}::{handler['componentName']}::{file_path}"

            seen_handlers.add(eh_uid)
            ingestion.ingest_event_handler(handler, file_path)


def _ingest_function_state(file_path: str, llm_results: dict) -> None:
    """Create State_Variable nodes + DECLARES_STATE edges for FC/hooks."""
    state_data = llm_results.get("state_function", {})
    for sv in state_data.get("stateVariables", []):
        if sv.get("name") and sv.get("componentName"):
            ingestion.ingest_function_state(sv, file_path)


def _ingest_class_state(file_path: str, llm_results: dict) -> None:
    """Create State_Variable nodes + DECLARES_CLASS_STATE edges for CC."""
    state_data = llm_results.get("state_class", {})
    for sv in state_data.get("classStateVariables", []):
        if sv.get("name") and sv.get("componentName"):
            ingestion.ingest_class_state(sv, file_path)


def _ingest_contexts(file_path: str, llm_results: dict) -> None:
    """Create Context nodes."""
    ctx_data = llm_results.get("contexts", {})
    for ctx in ctx_data.get("contexts", []):
        if ctx.get("name"):
            ingestion.ingest_context(ctx, file_path)
