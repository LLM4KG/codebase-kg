"""Batch ingestion orchestration — runs Cypher MERGE queries against Memgraph."""

from __future__ import annotations

import logging

from src.graph.connection import run_query_void
from src.graph import queries as Q

logger = logging.getLogger(__name__)


def ingest_project(project: dict) -> None:
    run_query_void(Q.MERGE_PROJECT, project)


def ingest_files_batch(files: list[dict], project_id: str) -> None:
    run_query_void(Q.MERGE_FILE_BATCH, {"files": files})
    file_paths = [f["filePath"] for f in files]
    run_query_void(Q.MERGE_BELONGS_TO_BATCH, {
        "filePaths": file_paths,
        "projectId": project_id,
    })


def ingest_libraries_batch(libraries: list[tuple[dict, str]], project_id: str) -> None:
    lib_params = [{"name": lib["name"], "version": lib["version"], "category": lib["category"]}
                  for lib, _ in libraries]
    run_query_void(Q.MERGE_LIBRARY_BATCH, {"libraries": lib_params})

    dep_params = [{"name": lib["name"], "dependencyType": dep_type}
                  for lib, dep_type in libraries]
    run_query_void(Q.MERGE_DEPENDS_ON_BATCH, {
        "deps": dep_params,
        "projectId": project_id,
    })


def ingest_function_component(comp: dict, file_path: str) -> None:
    uid = f"{comp['name']}::{file_path}"
    run_query_void(Q.MERGE_FUNCTION_COMPONENT, {
        "uid": uid, "name": comp["name"], "filePath": file_path,
        "syntax": comp.get("syntax", "function"),
        "usesHooks": comp.get("usesHooks", False),
        "returnsJSX": comp.get("returnsJSX", True),
        "exportType": comp.get("exportType", "none"),
    })
    run_query_void(Q.MERGE_DEFINED_IN_FC, {"compUid": uid, "filePath": file_path})


def ingest_custom_hook_as_node(comp: dict, file_path: str) -> None:
    uid = f"{comp['name']}::{file_path}"
    run_query_void(Q.MERGE_CUSTOM_HOOK, {
        "uid": uid, "name": comp["name"],
        "filePath": file_path,
        "exportType": comp.get("exportType", "none"),
    })
    run_query_void(Q.MERGE_DEFINED_IN_CUSTOM_HOOK, {"hookUid": uid, "filePath": file_path})


def ingest_class_component(comp: dict, file_path: str) -> None:
    uid = f"{comp['name']}::{file_path}"
    run_query_void(Q.MERGE_CLASS_COMPONENT, {
        "uid": uid, "name": comp["name"], "filePath": file_path,
        "extendsClass": comp.get("extendsClass", "React.Component"),
        "returnsJSX": comp.get("returnsJSX", True),
        "exportType": comp.get("exportType", "none"),
        "hasConstructor": comp.get("hasConstructor", False),
        "lifecycleMethods": comp.get("lifecycleMethods", []),
    })
    run_query_void(Q.MERGE_DEFINED_IN_CC, {"compUid": uid, "filePath": file_path})


def ingest_library_hook(hook: dict, comp_uid: str, count: int = 1) -> None:
    """Create the Library_Hook node and the USES_LIBRARY_HOOK edge.

    `count` is the number of call sites within the component, per the schema
    (§2.4). The caller counts them: `hookDetails` carries one entry per call
    site, so the tally belongs where that list is walked. It was hardcoded to 1
    here for every edge, which made the property meaningless across all three
    extracted projects — 16 of 59 edges were understated, by up to 4x.

    MERGE...SET overwrites rather than accumulates, so re-ingesting is safe.
    """
    hook_uid = f"{hook['name']}::{hook['source']}"
    run_query_void(Q.MERGE_LIBRARY_HOOK, {
        "uid": hook_uid, "name": hook["name"], "source": hook["source"],
    })
    run_query_void(Q.MERGE_FC_USES_LIBRARY_HOOK, {
        "compUid": comp_uid, "hookUid": hook_uid, "count": count,
    })


def ingest_custom_hook_usage(hook: dict, comp_uid: str, file_path: str,
                             file_manifest: list[str],
                             aliases: dict[str, str] | None = None,
                             base_url: str = "") -> None:
    """Create USES_CUSTOM_HOOK edge from FC to Custom_Hook.

    Resolution goes through the shared relative → alias → baseUrl ladder. The old
    code handled only relative sources and fell through to using the raw import
    string as a file path, so a bare specifier (`contexts/cart-context`) produced a
    uid pointing at no file and the MATCH-based MERGE silently did nothing.
    """
    from src.extraction.cross_file import resolve_to_manifest_file

    if hook["source"] == "local":
        hook_file = file_path
    else:
        # symbol_name lets a barrel import (`from 'contexts/cart-context'`) resolve
        # past index.ts to the file that actually defines the hook.
        hook_file = resolve_to_manifest_file(
            hook["source"], file_path, file_manifest, aliases, base_url,
            symbol_name=hook["name"],
        )
        if hook_file is None:
            hook_file = hook["source"]
            logger.warning("Could not resolve custom hook '%s' from '%s'",
                           hook["name"], hook["source"])

    hook_uid = f"{hook['name']}::{hook_file}"
    run_query_void(Q.MERGE_FC_USES_CUSTOM_HOOK, {
        "compUid": comp_uid, "hookUid": hook_uid,
    })


def ingest_prop(prop: dict, file_path: str) -> None:
    prop_uid = f"{prop['name']}::{prop['componentName']}::{file_path}"
    comp_uid = f"{prop['componentName']}::{file_path}"
    run_query_void(Q.MERGE_PROP, {
        "uid": prop_uid, "name": prop["name"],
        "componentName": prop["componentName"],
        "filePath": file_path, "type": prop.get("type", "unknown"),
        "isRequired": prop.get("isRequired"),
    })
    run_query_void(Q.MERGE_ACCEPTS_PROP, {
        "compUid": comp_uid, "propUid": prop_uid,
    })


def ingest_event_handler(handler: dict, file_path: str) -> None:
    eh_uid = f"{handler['name']}::{handler['componentName']}::{file_path}"
    comp_uid = f"{handler['componentName']}::{file_path}"
    run_query_void(Q.MERGE_EVENT_HANDLER, {
        "uid": eh_uid, "name": handler["name"],
        "eventType": handler["eventType"], "filePath": file_path,
        "componentName": handler["componentName"],
        "isInline": handler.get("isInline", False),
    })
    run_query_void(Q.MERGE_HAS_HANDLER, {
        "compUid": comp_uid, "ehUid": eh_uid,
    })


def ingest_function_state(sv: dict, file_path: str) -> None:
    from src.extraction.per_file_ingestion import is_custom_hook_name, check_is_literal

    owner = sv["componentName"]
    sv_uid = f"{sv['name']}::{owner}::{file_path}"
    source_uid = f"{owner}::{file_path}"
    init_is_literal = check_is_literal(sv.get("defaultValue", "undefined"))

    run_query_void(Q.MERGE_STATE_VARIABLE, {
        "uid": sv_uid, "name": sv["name"], "setterName": sv["setterName"],
        "type": sv.get("type", "unknown"),
        "defaultValue": sv.get("defaultValue", "undefined"),
        "filePath": file_path, "componentName": owner,
    })

    if is_custom_hook_name(owner):
        run_query_void(Q.MERGE_CUSTOM_HOOK_DECLARES_STATE, {
            "sourceUid": source_uid, "svUid": sv_uid,
            "initIsLiteral": init_is_literal,
        })
    else:
        run_query_void(Q.MERGE_DECLARES_STATE, {
            "sourceUid": source_uid, "svUid": sv_uid,
            "initIsLiteral": init_is_literal,
        })


def ingest_class_state(sv: dict, file_path: str) -> None:
    owner = sv["componentName"]
    sv_uid = f"{sv['name']}::{owner}::{file_path}"
    comp_uid = f"{owner}::{file_path}"

    run_query_void(Q.MERGE_STATE_VARIABLE, {
        "uid": sv_uid, "name": sv["name"],
        "setterName": sv.get("setterName", "this.setState"),
        "type": sv.get("type", "unknown"),
        "defaultValue": sv.get("defaultValue", "undefined"),
        "filePath": file_path, "componentName": owner,
    })
    run_query_void(Q.MERGE_DECLARES_CLASS_STATE, {
        "compUid": comp_uid, "svUid": sv_uid,
        "declarationStyle": sv.get("declarationStyle", "constructor"),
    })


def ingest_context(ctx: dict, file_path: str) -> None:
    ctx_uid = f"{ctx['name']}::{file_path}"
    run_query_void(Q.MERGE_CONTEXT, {
        "uid": ctx_uid, "name": ctx["name"], "filePath": file_path,
        "defaultValue": ctx.get("defaultValue", "undefined"),
        "exportType": ctx.get("exportType", "none"),
    })


def _find_matching_file(base_path: str, file_manifest: list[str]) -> str | None:
    from src.extraction.cross_file import expand_extensions
    candidates = expand_extensions(base_path)
    for candidate in candidates:
        if candidate in file_manifest:
            return candidate
    return None
