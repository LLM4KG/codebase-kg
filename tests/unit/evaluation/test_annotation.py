"""WP6 annotation set: dump reader, item identities, file format, sampling."""

from pathlib import Path

import pytest

from src.evaluation.annotation import (
    Endpoint,
    Header,
    Item,
    ItemSyntaxError,
    coverage_types,
    items_by_evidence_file,
    parse_annotation_file,
    parse_item,
    render_annotation_file,
    sample_files,
)
from src.evaluation.kg_dump import load_dump

APP = "src/App.tsx"
BTN = "src/Button.tsx"

# A small dump in Memgraph's DUMP DATABASE format.
DUMP = r"""CREATE INDEX ON :__mg_vertex__(__mg_id__);
CREATE (:__mg_vertex__:`Project` {__mg_id__: 0, `projectId`: "demo", `name`: "demo"});
CREATE (:__mg_vertex__:`File` {__mg_id__: 1, `filePath`: "src/App.tsx", `name`: "App.tsx"});
CREATE (:__mg_vertex__:`File` {__mg_id__: 2, `filePath`: "src/Button.tsx", `name`: "Button.tsx"});
CREATE (:__mg_vertex__:`File` {__mg_id__: 3, `filePath`: "src/index.ts", `name`: "index.ts"});
CREATE (:__mg_vertex__:`Function_Component` {__mg_id__: 4, `filePath`: "src/App.tsx", `uid`: "App::src/App.tsx", `name`: "App"});
CREATE (:__mg_vertex__:`Function_Component` {__mg_id__: 5, `filePath`: "src/Button.tsx", `uid`: "Button::src/Button.tsx", `name`: "Button"});
CREATE (:__mg_vertex__:`Prop` {__mg_id__: 6, `filePath`: "src/Button.tsx", `uid`: "onClick::Button::src/Button.tsx", `name`: "onClick", `componentName`: "Button", `isRequired`: true});
CREATE (:__mg_vertex__:`EventHandler` {__mg_id__: 7, `filePath`: "src/Button.tsx", `uid`: "modal.close::Form.Field::src/Button.tsx", `name`: "modal.close", `componentName`: "Form.Field", `default`: "\'x\'"});
CREATE (:__mg_vertex__:`Library_Hook` {__mg_id__: 8, `uid`: "useState::react", `name`: "useState", `source`: "react"});
CREATE (:__mg_vertex__:`Library` {__mg_id__: 9, `name`: "react", `version`: "18"});
MATCH (u:__mg_vertex__), (v:__mg_vertex__) WHERE u.__mg_id__ = 1 AND v.__mg_id__ = 0 CREATE (u)-[:`BELONGS_TO`]->(v);
MATCH (u:__mg_vertex__), (v:__mg_vertex__) WHERE u.__mg_id__ = 2 AND v.__mg_id__ = 0 CREATE (u)-[:`BELONGS_TO`]->(v);
MATCH (u:__mg_vertex__), (v:__mg_vertex__) WHERE u.__mg_id__ = 3 AND v.__mg_id__ = 0 CREATE (u)-[:`BELONGS_TO`]->(v);
MATCH (u:__mg_vertex__), (v:__mg_vertex__) WHERE u.__mg_id__ = 4 AND v.__mg_id__ = 5 CREATE (u)-[:`USES_COMPONENT`]->(v);
MATCH (u:__mg_vertex__), (v:__mg_vertex__) WHERE u.__mg_id__ = 4 AND v.__mg_id__ = 5 CREATE (u)-[:`PASSES_PROP` {`propName`: "onClick"}]->(v);
MATCH (u:__mg_vertex__), (v:__mg_vertex__) WHERE u.__mg_id__ = 4 AND v.__mg_id__ = 5 CREATE (u)-[:`PASSES_PROP` {`propName`: "label"}]->(v);
MATCH (u:__mg_vertex__), (v:__mg_vertex__) WHERE u.__mg_id__ = 5 AND v.__mg_id__ = 6 CREATE (u)-[:`ACCEPTS_PROP`]->(v);
MATCH (u:__mg_vertex__), (v:__mg_vertex__) WHERE u.__mg_id__ = 4 AND v.__mg_id__ = 8 CREATE (u)-[:`USES_LIBRARY_HOOK` {`count`: 1}]->(v);
MATCH (u:__mg_vertex__), (v:__mg_vertex__) WHERE u.__mg_id__ = 8 AND v.__mg_id__ = 9 CREATE (u)-[:`PROVIDED_BY`]->(v);
MATCH (u:__mg_vertex__), (v:__mg_vertex__) WHERE u.__mg_id__ = 0 AND v.__mg_id__ = 9 CREATE (u)-[:`DEPENDS_ON` {`dependencyType`: "production"}]->(v);
MATCH (u:__mg_vertex__), (v:__mg_vertex__) WHERE u.__mg_id__ = 4 AND v.__mg_id__ = 4 CREATE (u)-[:`ROUTES_TO` {`path`: "/a b"}]->(v);
DROP INDEX ON :__mg_vertex__(__mg_id__);
"""


@pytest.fixture
def graph(tmp_path: Path):
    p = tmp_path / "full_dump.cypherl"
    p.write_text(DUMP, encoding="utf-8")
    return load_dump(p)


# --------------------------------------------------------------------------- #
# Dump reader                                                                 #
# --------------------------------------------------------------------------- #
def test_load_dump_reads_nodes_edges_and_property_types(graph):
    assert len(graph.nodes) == 10
    assert len(graph.edges) == 11
    assert graph.nodes[6].props["isRequired"] is True
    assert graph.nodes[7].props["default"] == "'x'"  # Memgraph's \' escape
    assert graph.files() == [APP, BTN, "src/index.ts"]
    assert {e.type for e in graph.edges if e.src == 4 and e.dst == 5} == {"USES_COMPONENT", "PASSES_PROP"}


# --------------------------------------------------------------------------- #
# Evidence files                                                              #
# --------------------------------------------------------------------------- #
def test_edges_go_to_their_source_endpoints_file(graph):
    s = items_by_evidence_file(graph)
    app = {i.text(APP) for i in s.by_file[APP]}
    btn = {i.text(BTN) for i in s.by_file[BTN]}
    # App -> Button edges are stated in App.tsx, not Button.tsx.
    assert f"E USES_COMPONENT Function_Component:App -> Function_Component:Button@{BTN}" in app
    assert not any("USES_COMPONENT" in t for t in btn)
    assert "E ACCEPTS_PROP Function_Component:Button -> Prop:Button::onClick" in btn


def test_passes_prop_multi_edges_are_distinct_items(graph):
    app = items_by_evidence_file(graph).by_file[APP]
    keys = sorted(i.key for i in app if i.rel == "PASSES_PROP")
    assert keys == [("prop", "label"), ("prop", "onClick")]


def test_provided_by_goes_to_every_hook_user_and_package_items_are_separate(graph):
    s = items_by_evidence_file(graph)
    assert any(i.rel == "PROVIDED_BY" for i in s.by_file[APP])
    assert not any(i.rel == "PROVIDED_BY" for i in s.by_file[BTN])
    assert {i.type for i in s.package} == {"Project", "Library", "DEPENDS_ON"}
    # A file with nothing but its File node and BELONGS_TO still gets an entry.
    assert {i.type for i in s.by_file["src/index.ts"]} == {"File", "BELONGS_TO"}


def test_scopes(graph):
    items = items_by_evidence_file(graph).by_file[APP]
    scope = {i.type: i.scope for i in items}
    assert scope["File"] == scope["BELONGS_TO"] == scope["PROVIDED_BY"] == "deterministic"
    assert scope["Function_Component"] == scope["USES_LIBRARY_HOOK"] == "llm"


def test_coverage_types_skip_universal_types_and_count_library_hook(graph):
    types = coverage_types(items_by_evidence_file(graph).by_file[APP])
    assert "File" not in types and "BELONGS_TO" not in types
    assert {"Library_Hook", "USES_LIBRARY_HOOK", "ROUTES_TO"} <= types


# --------------------------------------------------------------------------- #
# Item syntax                                                                 #
# --------------------------------------------------------------------------- #
def test_owned_names_split_on_the_uid_separator_both_parts_may_be_dotted():
    item = parse_item("N EventHandler:Form.Field::modal.close", BTN)
    assert item.src == Endpoint("EventHandler", "modal.close", "Form.Field", BTN)
    assert item.text(BTN) == "N EventHandler:Form.Field::modal.close"


def test_path_defaults_to_this_file_and_is_elided_when_rendering():
    item = parse_item("N Function_Component:App", APP)
    assert item.src.loc == APP
    assert item.text(APP) == "N Function_Component:App"
    assert item.text(BTN) == f"N Function_Component:App@{APP}"


def test_edge_keys_with_spaces_round_trip():
    item = Item("E", Endpoint("Function_Component", "App", None, APP), "ROUTES_TO",
                Endpoint("Function_Component", "App", None, APP), ("path", "/a b"))
    assert parse_item(item.text(APP), APP) == item


@pytest.mark.parametrize("text, message", [
    ("X Function_Component:App", "starts with N"),
    ("N Prop:onClick", "Owner::name"),
    ("N Library_Hook:useState", "source"),
    ("N File:App", "no name"),
    ("N Widget:App", "unknown node type"),
    ("E PASSES_PROP Function_Component:App -> Function_Component:B", "prop="),
    ("E USES_COMPONENT Function_Component:App Function_Component:B", "E REL Source -> Target"),
    ("E USES_COMPONENT Function_Component:App -> Function_Component:B prop=x", "takes no key"),
])
def test_malformed_items_are_rejected_with_a_helpful_message(text, message):
    with pytest.raises(ItemSyntaxError, match=message):
        parse_item(text, APP)


# --------------------------------------------------------------------------- #
# Annotation file                                                             #
# --------------------------------------------------------------------------- #
def _render(graph, path=APP, source="export const App = () => null\n"):
    items = items_by_evidence_file(graph).by_file[path]
    header = Header("demo", path, "a" * 40, "ps1", "graph_export/demo/full_dump.cypherl")
    return items, render_annotation_file(header, source, items, "tsx")


def test_rendered_file_parses_back_to_exactly_the_kg_items(graph):
    items, text = _render(graph)
    parsed = parse_annotation_file(text)
    assert (parsed.project, parsed.path, parsed.status) == ("demo", APP, "todo")
    assert sorted(i for i, _, _ in parsed.decisions) == sorted(items)
    assert all(v == "undecided" for _, v, _ in parsed.decisions)
    assert parsed.missed == [] and parsed.errors == []
    assert not parsed.complete


def test_source_lines_that_look_like_items_are_ignored(graph):
    _, text = _render(graph, source="- [ ] N Function_Component:Fake\nN Prop:X::y\n")
    names = {i.src.name for i, _, _ in parse_annotation_file(text).decisions}
    assert "Fake" not in names


def test_verdicts_notes_and_missed_items_are_parsed(graph):
    _, text = _render(graph)
    text = text.replace("- [ ] N Function_Component:App", "- [y] N Function_Component:App # looks fine", 1)
    text = text.replace("- [ ] E USES_COMPONENT", "- [n] E USES_COMPONENT", 1)
    text = text.replace("- [ ] E ROUTES_TO", "- [?] E ROUTES_TO", 1)
    text = text.replace(
        "<!-- wp6:missed -->\n",
        "<!-- wp6:missed -->\n- N Prop:App::title # cause: llm\n"
        "E USES_COMPONENT Function_Component:App -> Function_Component:Icon@src/Icon.tsx\n",
    )
    parsed = parse_annotation_file(text)
    verdict = {i.type: (v, note) for i, v, note in parsed.decisions}
    assert verdict["Function_Component"] == ("correct", "looks fine")
    assert verdict["USES_COMPONENT"][0] == "wrong"
    assert verdict["ROUTES_TO"][0] == "unsure"
    assert [(i.text(APP), note) for i, note in parsed.missed] == [
        ("N Prop:App::title", "cause: llm"),
        ("E USES_COMPONENT Function_Component:App -> Function_Component:Icon@src/Icon.tsx", None),
    ]
    assert parsed.errors == []


def test_bad_verdicts_and_bad_missed_lines_are_reported_not_dropped(graph):
    _, text = _render(graph)
    text = text.replace("- [ ] N Function_Component:App", "- [k] N Function_Component:App", 1)
    text = text.replace("<!-- wp6:missed -->\n", "<!-- wp6:missed -->\nN Prop:title\n")
    errors = parse_annotation_file(text).errors
    assert len(errors) == 2
    assert "verdict [k]" in errors[0] and "Owner::name" in errors[1]


def test_complete_needs_done_status_and_every_item_decided(graph):
    _, text = _render(graph)
    decided = text.replace("- [ ] ", "- [y] ")
    assert not parse_annotation_file(decided).complete  # status still todo
    assert parse_annotation_file(decided.replace("status: todo", "status: done")).complete


# --------------------------------------------------------------------------- #
# Sampling                                                                    #
# --------------------------------------------------------------------------- #
TYPES = {
    "a": {f"a{i}.ts": ({"Prop"} if i < 5 else set()) for i in range(10)} | {"a_rare.ts": {"ROUTES_TO"}},
    "b": {f"b{i}.ts": {"Prop", "HAS_HANDLER"} for i in range(8)} | {"b_empty.ts": set()},
}
EMPTY = {"a": {f"a{i}.ts" for i in range(5, 10)}, "b": {"b_empty.ts"}}


def _sample(seed=7):
    return sample_files(TYPES, {"a": 3, "b": 3}, seed, ["a", "b"], EMPTY, 1)


def test_sampling_is_deterministic_and_respects_quotas():
    picks = _sample()
    assert picks == _sample()
    assert sum(p.project == "a" for p in picks) == 3
    assert sum(p.project == "b" for p in picks) == 3


def test_sampling_covers_every_type_and_takes_the_rare_one():
    picks = _sample()
    covered = set().union(*(TYPES[p.project][p.path] for p in picks))
    assert covered == {"Prop", "ROUTES_TO", "HAS_HANDLER"}
    assert any(p.path == "a_rare.ts" and p.reason == "covers ROUTES_TO" for p in picks)


def test_each_project_gets_exactly_one_no_item_file():
    for seed in range(20):
        picks = sample_files(TYPES, {"a": 3, "b": 3}, seed, ["a", "b"], EMPTY, 1)
        for proj in ("a", "b"):
            assert sum(p.path in EMPTY[proj] for p in picks if p.project == proj) == 1


def test_picks_are_ordered_project_by_project_then_by_path():
    picks = _sample()
    assert [p.project for p in picks] == ["a"] * 3 + ["b"] * 3
    assert [p.path for p in picks[:3]] == sorted(p.path for p in picks[:3])
