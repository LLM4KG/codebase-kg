"""Stage 4: Post-extraction cross-file resolution."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path, PurePosixPath

from src.graph.connection import run_query, run_query_void
from src.graph import queries as Q
from src.extraction.llm_extractor import CROSS_FILE_PROMPTS, extract_file_cross_file
from src.llm.extraction_log import ExtractionRunLog

logger = logging.getLogger(__name__)

EXTENSIONS = [".jsx", ".js", ".tsx", ".ts"]

KNOWN_WRAPPERS = {
    "StrictMode", "React.StrictMode",
    "Provider", "BrowserRouter", "HashRouter", "MemoryRouter", "Router",
    "QueryClientProvider", "ThemeProvider", "PersistGate",
    "Suspense", "ErrorBoundary",
}

CANDIDATE_ENTRYPOINTS = [
    "src/index.jsx", "src/index.js", "src/index.tsx", "src/index.ts",
    "src/main.jsx", "src/main.js", "src/main.tsx", "src/main.ts",
    "index.jsx", "index.js", "index.tsx", "index.ts",
]


def resolve_alias(import_source: str, aliases: dict[str, str]) -> str | None:
    """Resolve an alias-prefixed import to a repo-relative base path.

    Alias keys are checked longest-first so that "@resources" matches
    before "@" when both are present.  Returns None if no alias matches.
    """
    if not aliases:
        return None
    for prefix in sorted(aliases, key=len, reverse=True):
        if import_source == prefix:
            return aliases[prefix]
        if import_source.startswith(prefix + "/"):
            return aliases[prefix] + import_source[len(prefix):]
    return None


def resolve_relative_import(import_source: str, current_file: str) -> str:
    """Resolve a relative import path to a repo-relative base path."""
    current_dir = str(PurePosixPath(current_file).parent)
    joined = str(PurePosixPath(current_dir) / import_source)
    # Normalize the path (resolve ..)
    parts = []
    for part in joined.split("/"):
        if part == "..":
            if parts:
                parts.pop()
        elif part != ".":
            parts.append(part)
    return "/".join(parts)


def resolve_base_url(import_source: str, base_url: str) -> str | None:
    """Resolve a bare specifier against the project's `baseUrl`.

    `react-shopping-cart` sets `"baseUrl": "src"` in tsconfig.json and imports as
    `from 'contexts/cart-context'` / `from 'models'`. Those are neither relative
    nor alias-prefixed, so every resolver in the pipeline fell through to treating
    them as external packages — which is why its hooks became orphan `Library_Hook`
    nodes and its `USES_COMPONENT` count was zero.

    Returns None when the project declares no `base_url`, or when the specifier is
    relative (the caller handles that case first).
    """
    if not base_url or not import_source:
        return None
    if import_source.startswith("./") or import_source.startswith("../"):
        return None
    # Scoped/absolute package specifiers are never project-local.
    if import_source.startswith("@") or import_source.startswith("/"):
        return None
    return str(PurePosixPath(base_url) / import_source)


def resolve_import_path(
    import_source: str,
    current_file: str,
    aliases: dict[str, str] | None = None,
    base_url: str = "",
) -> str | None:
    """Resolve any import specifier to a repo-relative base path (no extension).

    Single ordering used by every consumer — relative, then alias, then baseUrl —
    so hook usage, component composition, custom-hook internals and context
    resolution cannot disagree about where an import points. Returns None if the
    specifier looks external.
    """
    if not import_source:
        return None

    if import_source.startswith("./") or import_source.startswith("../"):
        return resolve_relative_import(import_source, current_file)

    alias_resolved = resolve_alias(import_source, aliases or {})
    if alias_resolved is not None:
        return alias_resolved

    return resolve_base_url(import_source, base_url)


def resolve_to_manifest_file(
    import_source: str,
    current_file: str,
    file_manifest: list[str],
    aliases: dict[str, str] | None = None,
    base_url: str = "",
    symbol_name: str | None = None,
) -> str | None:
    """Resolve an import to an actual file in the manifest, or None.

    When the import lands on a barrel (`index.ts` doing `export { default } from
    './Loader'`) and a `symbol_name` is given, prefer the sibling file named after
    the symbol. react-shopping-cart uses a directory-per-component/hook layout with
    a barrel in every directory, so `from 'contexts/cart-context'` resolves to
    `index.ts` while the node lives in `useCart.ts` — and every MATCH-based MERGE
    against the barrel's uid was a silent no-op. takenote imports implementation
    files directly, which is why it was unaffected.

    Name-matching is a convention, not a parse: it works for `useCart -> useCart.ts`
    and `Loader -> Loader.tsx`, but not for a renaming re-export such as
    `export { CartProvider } from './CartContextProvider'`. Callers that hold a node
    index (see `resolve_child_component`) should prefer matching on the node's own
    name, which handles renames correctly.
    """
    base = resolve_import_path(import_source, current_file, aliases, base_url)
    if base is None:
        return None

    if symbol_name:
        for ext in EXTENSIONS:
            candidate = f"{base}/{symbol_name}{ext}"
            if candidate in file_manifest:
                return candidate

    for candidate in expand_extensions(base):
        if candidate in file_manifest:
            return candidate
    return None


def expand_extensions(base_path: str) -> list[str]:
    """Expand a base import path to possible file paths with extensions."""
    candidates = []
    for ext in EXTENSIONS:
        candidates.append(base_path + ext)
    for ext in EXTENSIONS:
        candidates.append(base_path + "/index" + ext)
    return candidates


def _build_component_index(file_manifest: list[str]) -> dict[str, dict]:
    """Query graph to build a lookup of all components by uid."""
    index: dict[str, dict] = {}

    # Function Components
    results = run_query("MATCH (fc:Function_Component) RETURN fc.uid AS uid, fc.name AS name, fc.filePath AS filePath, fc.exportType AS exportType")
    for r in results:
        index[r["uid"]] = {"uid": r["uid"], "name": r["name"], "filePath": r["filePath"], "type": "Function_Component", "exportType": r["exportType"]}

    # Class Components
    results = run_query("MATCH (cc:Class_Component) RETURN cc.uid AS uid, cc.name AS name, cc.filePath AS filePath, cc.exportType AS exportType")
    for r in results:
        index[r["uid"]] = {"uid": r["uid"], "name": r["name"], "filePath": r["filePath"], "type": "Class_Component", "exportType": r["exportType"]}

    # Custom Hooks
    results = run_query("MATCH (ch:Custom_Hook) RETURN ch.uid AS uid, ch.name AS name, ch.filePath AS filePath")
    for r in results:
        index[r["uid"]] = {"uid": r["uid"], "name": r["name"], "filePath": r["filePath"], "type": "Custom_Hook"}

    return index


def _build_context_index() -> dict[str, dict]:
    """Query graph to build a lookup of all contexts by uid."""
    index: dict[str, dict] = {}
    results = run_query("MATCH (ctx:Context) RETURN ctx.uid AS uid, ctx.name AS name, ctx.filePath AS filePath")
    for r in results:
        index[r["uid"]] = {"uid": r["uid"], "name": r["name"], "filePath": r["filePath"]}
    return index


def resolve_child_component(
    child_name: str,
    import_source: str,
    current_file: str,
    component_index: dict[str, dict],
    file_manifest: list[str],
    aliases: dict[str, str] | None = None,
    base_url: str = "",
) -> dict | None:
    """Resolve a child component name + import source to a graph node."""
    if import_source == "same_file":
        uid = f"{child_name}::{current_file}"
        return component_index.get(uid)

    # Relative → alias → baseUrl. The baseUrl leg is what makes bare specifiers
    # like `components/Cart` resolvable; without it every such child was dropped.
    resolved = resolve_import_path(import_source, current_file, aliases, base_url)
    if resolved is None:
        # External library component — not a project component
        return None

    for candidate in expand_extensions(resolved):
        uid = f"{child_name}::{candidate}"
        if uid in component_index:
            return component_index[uid]

    # Barrel indirection: the import landed on a directory whose `index.*` merely
    # re-exports. Match on the node's own name anywhere directly beneath that
    # directory — which also resolves renaming re-exports like
    # `export { CartProvider } from './CartContextProvider'`, where no filename
    # matches the imported symbol.
    found = _find_component_under_directory(child_name, resolved, component_index)
    if found is not None:
        return found

    # Renamed default import: `import Board from './Board'` where Board/index.jsx
    # defines `ProjectBoard`. The JSX tag carries the importer's local name, which
    # need not match the node. If the import lands on a file that defines exactly
    # one component, a default import can only mean that one (jira_clone names
    # nearly every component this way). Files with several components stay
    # unresolved rather than guessed.
    return _sole_component_in_file(resolved, component_index, file_manifest)


def _sole_component_in_file(
    resolved: str,
    component_index: dict[str, dict],
    file_manifest: list[str],
) -> dict | None:
    """The only component defined in the file `resolved` points at, else None.

    Custom hooks share the component index but cannot be a JSX child, so they
    neither count as the sole component nor stop one from being sole.
    """
    target = next((c for c in expand_extensions(resolved) if c in file_manifest), None)
    if target is None:
        return None
    in_file = [
        e for e in component_index.values()
        if e.get("filePath") == target and e.get("type") != "Custom_Hook"
    ]
    if len(in_file) == 1:
        return in_file[0]
    # Several components (jira_clone's IssueCreate also defines render helpers):
    # a default import can only mean the file's single default export.
    defaults = [e for e in in_file if e.get("exportType") == "default"]
    return defaults[0] if len(defaults) == 1 else None


def _find_component_under_directory(
    name: str,
    directory: str,
    component_index: dict[str, dict],
) -> dict | None:
    """Find a component by name whose file sits directly inside `directory`.

    Restricted to direct children so that a barrel does not accidentally claim a
    same-named component from a nested sub-directory. One nested shape is
    accepted: `<directory>/<name>/index.*`, the folder-per-component layout
    behind `export { default as Button } from './Button'` (jira_clone's
    `shared/components`). It is what `./Button` itself resolves to, so it is the
    re-export target rather than an unrelated same-named component. Without it,
    every barrel import of a folder component was dropped.
    """
    prefix = directory.rstrip("/") + "/"
    folder_index = tuple(f"{prefix}{name}/index{ext}" for ext in EXTENSIONS)
    for entry in component_index.values():
        if entry["name"] != name:
            continue
        file_path = entry.get("filePath") or ""
        if not file_path.startswith(prefix):
            continue
        if "/" in file_path[len(prefix):] and file_path not in folder_index:
            continue  # nested deeper than one level
        return entry
    return None


def resolve_context(
    context_name: str,
    context_source: str,
    current_file: str,
    context_index: dict[str, dict],
    aliases: dict[str, str] | None = None,
    base_url: str = "",
) -> dict | None:
    """Resolve a context name + source to a Context node."""
    if context_source == "same_file":
        uid = f"{context_name}::{current_file}"
        return context_index.get(uid)

    resolved = resolve_import_path(context_source, current_file, aliases, base_url)
    if resolved is None:
        return None

    for candidate in expand_extensions(resolved):
        uid = f"{context_name}::{candidate}"
        if uid in context_index:
            return context_index[uid]

    # Contexts sit behind barrels too — `createContext` lives in the provider file
    # while the import targets the directory.
    return _find_component_under_directory(context_name, resolved, context_index)


def _file_has_cross_file_content(llm_results: dict) -> bool:
    """Check whether Stage 2 results contain components, hooks, or contexts.

    The docstring always claimed "hooks", but there was no key carrying them: hook
    definitions were never extracted, so a hook-only file looked empty and was
    skipped. `custom_hook_internal.jinja2` — the Stage 4 prompt written
    specifically for hook files — therefore never ran on one, and hook→hook edges
    (`useCart` → `useCartProducts`) could not exist.
    """
    fc = llm_results.get("function_components", {})
    if fc.get("components"):
        return True
    hooks = llm_results.get("custom_hooks", {})
    if hooks.get("customHooks"):
        return True
    cc = llm_results.get("class_components", {})
    if cc.get("classComponents"):
        return True
    ctx = llm_results.get("contexts", {})
    if ctx.get("contexts"):
        return True
    return False


async def run_cross_file_extraction(
    repo_root: Path,
    file_paths: list[str],
    all_llm_results: dict[str, dict],
    on_progress: callable | None = None,
    aliases: dict[str, str] | None = None,
    base_url: str = "",
    raw_output_dir: Path | None = None,
    run_log: ExtractionRunLog | None = None,
) -> None:
    """
    Stage 4: Run cross-file LLM prompts and create cross-file edges.

    `raw_output_dir` persists each file's cross-file LLM responses to disk. Stage 2
    results have always been saved; Stage 4's were not, which is why a zero
    `USES_COMPONENT` count could not be attributed to either the prompt returning
    nothing or the resolver dropping what it returned.
    """
    file_manifest = file_paths
    component_index = _build_component_index(file_manifest)
    context_index = _build_context_index()

    relevant_files = [
        fp for fp in file_paths
        if _file_has_cross_file_content(all_llm_results.get(fp, {}))
    ]
    skipped = len(file_paths) - len(relevant_files)
    if skipped:
        logger.info("Stage 4: skipping %d files with no components/hooks/contexts", skipped)

    total_steps = len(relevant_files) * len(CROSS_FILE_PROMPTS) + 3  # +3 for post-processing
    step = 0

    # ── Run cross-file LLM prompts per file ──
    cross_file_results: dict[str, dict[str, dict]] = {}

    for fp in relevant_files:
        full_path = repo_root / fp
        if not full_path.exists():
            continue
        code = full_path.read_text(errors="replace")
        cross_file_results[fp] = {}

        for prompt_id, template, response_model in CROSS_FILE_PROMPTS:
            result = await extract_file_cross_file(
                fp, code, prompt_id, template, response_model, run_log=run_log
            )
            cross_file_results[fp][prompt_id] = result
            step += 1
            if on_progress:
                on_progress(step, total_steps, f"{fp}/{prompt_id}")

        _save_cross_file_raw(raw_output_dir, fp, cross_file_results[fp])

    # ── Ingest cross-file edges ──
    for fp, results in cross_file_results.items():
        _ingest_composition(fp, results.get("composition", {}),
                            component_index, file_manifest, aliases=aliases, base_url=base_url)
        _ingest_custom_hook_internal(fp, results.get("custom_hook_internal", {}),
                                     file_manifest, aliases=aliases, base_url=base_url)
        _ingest_context_relationships(fp, results.get("context_provider_consumer", {}),
                                      context_index, aliases=aliases, base_url=base_url)
        _ingest_routes(fp, results.get("route_definitions", {}),
                       component_index, file_manifest, aliases=aliases, base_url=base_url)

    # ── Deferred per-file edges that need the full node inventory ──
    _ingest_component_custom_hook_usage(
        all_llm_results, file_manifest, aliases=aliases, base_url=base_url
    )

    # ── Programmatic post-processing ──
    step += 1
    if on_progress:
        on_progress(step, total_steps, "entrypoint analysis")
    _extract_root_component(repo_root, component_index, file_manifest)

    step += 1
    if on_progress:
        on_progress(step, total_steps, "PROVIDED_BY edges")
    _create_provided_by_edges()

    step += 1
    if on_progress:
        on_progress(step, total_steps, "ANALYZE GRAPH")
    from src.graph.schema import analyze_graph
    analyze_graph()


def _ingest_component_custom_hook_usage(
    all_llm_results: dict[str, dict],
    file_manifest: list[str],
    aliases: dict[str, str] | None = None,
    base_url: str = "",
) -> None:
    """Create Function_Component → Custom_Hook edges once every node exists.

    Reads the Stage 2 `hookDetails` already in hand rather than making new LLM
    calls. Deferred out of Stage 3 because `MERGE_FC_USES_CUSTOM_HOOK` matches both
    endpoints and per-file ingestion runs in path order, so a component importing a
    hook defined later in the walk produced no edge at all.
    """
    # Imported inside the function on purpose: per_file_ingestion imports this
    # module at module level, so a top-level import here would close the cycle.
    # Do not hoist. (The durable fix is to move the shared resolution/naming
    # helpers into their own module; not done here to keep this change scoped.)
    from src.extraction.per_file_ingestion import is_custom_hook_name, recategorise_hook
    from src.graph import ingestion

    created = 0
    for file_path, results in all_llm_results.items():
        components = results.get("function_components", {}).get("components", [])
        for comp in components:
            name = comp.get("name", "")
            # A useXxx entry is a Custom_Hook node; hook-to-hook edges come from
            # the custom_hook_internal prompt instead.
            if not name or is_custom_hook_name(name):
                continue

            comp_uid = f"{name}::{file_path}"
            seen: set[str] = set()
            for hook in comp.get("hookDetails", []):
                key = f"{hook.get('name')}::{hook.get('source', '')}"
                if key in seen:
                    continue
                seen.add(key)

                if recategorise_hook(hook, file_path, file_manifest, aliases, base_url) != "custom":
                    continue
                ingestion.ingest_custom_hook_usage(
                    hook, comp_uid, file_path, file_manifest,
                    aliases=aliases, base_url=base_url,
                )
                created += 1

    logger.info("Stage 4: %d component→custom-hook usage edges attempted", created)


def _save_cross_file_raw(
    raw_output_dir: Path | None,
    file_path: str,
    results: dict[str, dict],
) -> None:
    """Persist one file's Stage 4 responses, mirroring the Stage 2 naming scheme."""
    if raw_output_dir is None:
        return
    try:
        raw_output_dir.mkdir(parents=True, exist_ok=True)
        safe_name = file_path.replace("/", "_").replace("\\", "_")
        (raw_output_dir / f"{safe_name}.json").write_text(json.dumps(results, indent=2))
    except OSError as exc:
        # Diagnostics must never abort an extraction run.
        logger.warning("Could not save cross-file raw output for %s: %s", file_path, exc)


def _ingest_composition(
    file_path: str,
    result: dict,
    component_index: dict[str, dict],
    file_manifest: list[str],
    aliases: dict[str, str] | None = None,
    base_url: str = "",
) -> None:
    """Create USES_COMPONENT and PASSES_PROP edges."""
    for usage in result.get("componentUsages", []):
        parent_uid = f"{usage['parentComponent']}::{file_path}"
        child_info = resolve_child_component(
            usage["childComponent"], usage["importSource"],
            file_path, component_index, file_manifest,
            aliases=aliases, base_url=base_url,
        )
        if child_info is None:
            continue

        child_uid = child_info["uid"]

        run_query_void(Q.MERGE_USES_COMPONENT, {
            "parentUid": parent_uid, "childUid": child_uid,
            "usage": usage.get("usage", "element"),
        })

        for prop in usage.get("propsPassed", []):
            run_query_void(Q.MERGE_PASSES_PROP, {
                "parentUid": parent_uid, "childUid": child_uid,
                "propName": prop["propName"],
            })


def _ingest_custom_hook_internal(
    file_path: str,
    result: dict,
    file_manifest: list[str],
    aliases: dict[str, str] | None = None,
    base_url: str = "",
) -> None:
    """Create Custom_Hook internal usage edges."""
    for entry in result.get("customHookUsages", []):
        hook_uid = f"{entry['hookName']}::{file_path}"

        for lh in entry.get("libraryHooks", []):
            lh_uid = f"{lh['name']}::{lh['source']}"
            run_query_void(Q.MERGE_CUSTOM_HOOK_USES_LIBRARY_HOOK, {
                "hookUid": hook_uid, "lhUid": lh_uid,
                "lhName": lh["name"], "lhSource": lh["source"],
                "count": lh.get("count", 1),
            })

        for ch in entry.get("customHooks", []):
            source = ch["source"]
            if source == "same_file":
                target_uid = f"{ch['name']}::{file_path}"
            else:
                # Falls back to the raw source when unresolvable, preserving the
                # previous behaviour: the MERGE is MATCH-based, so an unresolvable
                # target is a silent no-op rather than a bogus node.
                target_file = resolve_to_manifest_file(
                    source, file_path, file_manifest, aliases, base_url,
                    symbol_name=ch["name"],
                )
                target_uid = f"{ch['name']}::{target_file or source}"

            run_query_void(Q.MERGE_CUSTOM_HOOK_USES_CUSTOM_HOOK, {
                "sourceHookUid": hook_uid, "targetHookUid": target_uid,
            })


def _ingest_context_relationships(
    file_path: str,
    result: dict,
    context_index: dict[str, dict],
    aliases: dict[str, str] | None = None,
    base_url: str = "",
) -> None:
    """Create PROVIDES_CONTEXT and CONSUMES_CONTEXT edges."""
    for provider in result.get("contextProviders", []):
        comp_uid = f"{provider['componentName']}::{file_path}"
        ctx_info = resolve_context(
            provider["contextName"], provider["contextSource"],
            file_path, context_index, aliases=aliases, base_url=base_url,
        )
        if ctx_info is None:
            continue

        run_query_void(Q.MERGE_PROVIDES_CONTEXT, {
            "compUid": comp_uid, "ctxUid": ctx_info["uid"],
            "valueExpression": provider.get("valueExpression", ""),
        })

    for consumer in result.get("contextConsumers", []):
        consumer_uid = f"{consumer['consumerName']}::{file_path}"
        ctx_info = resolve_context(
            consumer["contextName"], consumer["contextSource"],
            file_path, context_index, aliases=aliases, base_url=base_url,
        )
        if ctx_info is None:
            continue

        consumer_type = consumer.get("consumerType", "function_component")
        if consumer_type == "class_component":
            run_query_void(Q.MERGE_CONSUMES_CONTEXT_CC, {
                "consumerUid": consumer_uid, "ctxUid": ctx_info["uid"],
            })
        elif consumer_type == "custom_hook":
            run_query_void(Q.MERGE_CONSUMES_CONTEXT_HOOK, {
                "consumerUid": consumer_uid, "ctxUid": ctx_info["uid"],
            })
        else:
            run_query_void(Q.MERGE_CONSUMES_CONTEXT_FC, {
                "consumerUid": consumer_uid, "ctxUid": ctx_info["uid"],
            })


def _ingest_routes(
    file_path: str,
    result: dict,
    component_index: dict[str, dict],
    file_manifest: list[str],
    aliases: dict[str, str] | None = None,
    base_url: str = "",
) -> None:
    """Create ROUTES_TO edges."""
    for route in result.get("routeDefinitions", []):
        source_uid = f"{route['routingComponent']}::{file_path}"
        target_info = resolve_child_component(
            route["targetComponent"], route["importSource"],
            file_path, component_index, file_manifest,
            aliases=aliases, base_url=base_url,
        )
        if target_info is None:
            continue

        run_query_void(Q.MERGE_ROUTES_TO, {
            "sourceUid": source_uid, "targetUid": target_info["uid"],
            "path": route["path"],
            "isNested": route.get("isNested", False),
            "isLazy": route.get("isLazy", False),
            "isProtected": route.get("isProtected", False),
        })


def find_entrypoint(
    repo_root: Path, file_manifest: list[str] | None = None
) -> tuple[str, str] | None:
    """Return `(entrypoint_path, root_component_name)`, or None.

    Candidates in order: package.json `main`, the conventional paths in
    CANDIDATE_ENTRYPOINTS, then (given a manifest) every other manifest file that
    imports react-dom, `index.*` / `main.*` first. The first candidate with a
    detectable render call wins.

    With a manifest, only extracted files are candidates. Previously the first
    candidate that merely *existed* was taken and never re-checked: takenote's
    `main` is `src/server/index.ts`, an excluded Express server, so detection
    looked there and failed, and the real `src/client/index.tsx` was never tried.
    """
    import json

    def eligible(path: str) -> bool:
        if file_manifest is not None:
            return path in file_manifest
        return (repo_root / path).is_file()

    candidates: list[str] = []
    pkg_path = repo_root / "package.json"
    if pkg_path.exists():
        main_field = json.loads(pkg_path.read_text()).get("main")
        if main_field:
            candidates.append(main_field)
    candidates += CANDIDATE_ENTRYPOINTS
    explicit = set(candidates)  # checked as before; the manifest scan below is filtered
    if file_manifest is not None:
        def _rank(path: str) -> tuple:
            stem = Path(path).stem
            return (stem not in ("index", "main"), path.count("/"), path)
        candidates += sorted(file_manifest, key=_rank)

    seen: set[str] = set()
    for path in candidates:
        if path in seen or not eligible(path):
            continue
        seen.add(path)
        content = (repo_root / path).read_text(errors="replace")
        if path not in explicit and "react-dom" not in content:
            continue
        root_name = _extract_rendered_component(content)
        if root_name is not None:
            return path, root_name
    return None


def _extract_root_component(
    repo_root: Path,
    component_index: dict[str, dict],
    file_manifest: list[str] | None = None,
) -> None:
    """Detect the root component from the entrypoint file."""
    found = find_entrypoint(repo_root, file_manifest)
    if found is None:
        logger.warning("Could not detect a root component (no entrypoint with a render call)")
        return
    entrypoint_path, root_name = found

    logger.info("Root component: %s (from %s)", root_name, entrypoint_path)

    run_query_void(Q.MERGE_RENDERS_ROOT_COMPONENT, {
        "entrypointPath": entrypoint_path,
        "rootComponentName": root_name,
    })
    run_query_void(Q.SET_IS_ROOT, {"rootComponentName": root_name})
    run_query_void(Q.SET_ALL_NOT_ROOT, {"rootComponentName": root_name})


def _extract_rendered_component(content: str) -> str | None:
    """Extract the root component name from a ReactDOM render call."""
    # Matches `root.render(`, `ReactDOM.render(` and the bare `render(` / `hydrate(`
    # of `import { render } from 'react-dom'` (todoist). The earlier patterns all
    # required a leading `.`, so a bare call went undetected and the graph got no
    # RENDERS_ROOT_COMPONENT edge. The lookbehind rejects identifiers that merely
    # end in "render", e.g. `rerender(`.
    render_call = r"(?<![\w$])(?:render|hydrate)\("

    match = re.search(render_call + r"\s*<(\w+)[\s/>]", content)
    if match:
        name = match.group(1)
        if name not in KNOWN_WRAPPERS and not name.startswith("React"):
            return name

    # Wrapper-aware fallback: find the render block and all JSX tags
    render_match = re.search(render_call, content)
    if render_match:
        # Extract a generous block after .render(
        start = render_match.start()
        block = content[start:start + 2000]
        all_tags = re.findall(r"<([A-Z]\w*)", block)
        candidates = [t for t in all_tags if t not in KNOWN_WRAPPERS and not t.startswith("React")]
        if len(candidates) >= 1:
            return candidates[-1]

    return None


def _create_provided_by_edges() -> None:
    """Create Library_Hook → PROVIDED_BY → Library edges."""
    run_query_void(Q.MERGE_PROVIDED_BY)
    logger.info("PROVIDED_BY edges created")
