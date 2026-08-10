"""Tests for neighbour props/state reaching the rendered context.

The 2026-07-30 re-measurement left P2 as the only kg_augmented failure, and all
five replicates died the same way:

    NoteList.tsx(172,14) TS2741: Property 'dataTestID' is missing in type
        '{ children; label; handler }' but required in type 'NoteListButtonProps'

`dataTestID` was in the KG the whole time. The primary templates returned
neighbours as {name, filePath}, so "Related Components" rendered a heading and a
path — information the anchor's own import list already carried. The whole-file
oracle, which sees the component body, passed P2 5/5.
"""

from pathlib import Path

from src.retrieval.assembler import (
    _Assembly,
    _build_bug_fix,
    _build_feature_addition,
    _build_refactoring,
    _clear_neighbor_props,
    _metadata_neighbor,
    _neighbor_uid,
    _removal_steps,
    assemble_context,
)
from src.retrieval.kg_retriever import KGAugmentedRetriever
from src.retrieval.models import ComponentContext, ContextData
from src.retrieval.renderer import ContextRenderer

TEMPLATE = Path("src/retrieval/templates/neighbor_props.cypher").read_text()

# The real shape: NoteListButton as the KG holds it.
NOTE_LIST_BUTTON_UID = "NoteListButton::src/client/components/NoteList/NoteListButton.tsx"
NOTE_LIST_BUTTON_PROPS = {
    "props": [
        {"name": "dataTestID", "type": "string", "isRequired": True},
        {"name": "handler", "type": "() => void", "isRequired": True},
        {"name": "label", "type": "string", "isRequired": False},
    ],
    "stateVars": [],
}


def _button_entry(with_uid: bool = True) -> dict:
    entry = {
        "name": "NoteListButton",
        "filePath": "src/client/components/NoteList/NoteListButton.tsx",
    }
    if with_uid:
        entry["uid"] = NOTE_LIST_BUTTON_UID
    return entry


class TestTemplateShape:
    def test_takes_neighbor_uids_and_project(self):
        assert "$neighborUids" in TEMPLATE
        assert "$projectId" in TEMPLATE

    def test_returns_uid_props_and_state(self):
        for field in ("AS uid", "AS props", "AS stateVars"):
            assert field in TEMPLATE

    def test_covers_both_state_relationships(self):
        """Function components DECLARE_STATE; class components DECLARES_CLASS_STATE."""
        assert "DECLARES_STATE|DECLARES_CLASS_STATE" in TEMPLATE

    def test_selects_is_required(self):
        """Required-ness is the part that breaks the build — TS2741, not TS2339."""
        assert "isRequired" in TEMPLATE

    def test_no_nested_aggregation(self):
        """Same constraint as refactoring_caller_props: one level of collect()."""
        assert "collect(DISTINCT collect" not in TEMPLATE


class TestNeighborUid:
    def test_prefers_the_uid_the_query_returned(self):
        assert _neighbor_uid(_button_entry()) == NOTE_LIST_BUTTON_UID

    def test_falls_back_to_the_composite_convention(self):
        """A template whose collect() omits uid must still join, not lose its props."""
        assert _neighbor_uid(_button_entry(with_uid=False)) == NOTE_LIST_BUTTON_UID

    def test_empty_when_unkeyable(self):
        assert _neighbor_uid({"name": "Orphan"}) == ""
        assert _neighbor_uid({}) == ""


class TestMetadataNeighborMerge:
    def test_merges_props_and_state(self):
        cc = _metadata_neighbor(_button_entry(), {NOTE_LIST_BUTTON_UID: NOTE_LIST_BUTTON_PROPS})
        assert [p["name"] for p in cc.props] == ["dataTestID", "handler", "label"]

    def test_required_props_computed(self):
        cc = _metadata_neighbor(_button_entry(), {NOTE_LIST_BUTTON_UID: NOTE_LIST_BUTTON_PROPS})
        assert cc.required_props == ["dataTestID", "handler"]

    def test_required_props_survive_model_dump(self):
        """A plain @property would vanish in model_dump(), which is how the
        renderer passes data to the template — hence computed_field."""
        cc = _metadata_neighbor(_button_entry(), {NOTE_LIST_BUTTON_UID: NOTE_LIST_BUTTON_PROPS})
        assert cc.model_dump()["required_props"] == ["dataTestID", "handler"]

    def test_absent_map_is_the_old_behaviour(self):
        cc = _metadata_neighbor(_button_entry())
        assert cc.props == [] and cc.state_variables == [] and cc.required_props == []

    def test_unmatched_uid_does_not_borrow_another_neighbours_props(self):
        cc = _metadata_neighbor(
            {"name": "SearchBar", "filePath": "src/client/components/NoteList/SearchBar.tsx"},
            {NOTE_LIST_BUTTON_UID: NOTE_LIST_BUTTON_PROPS},
        )
        assert cc.props == []

    def test_null_collect_placeholders_dropped(self):
        """Memgraph's collect() over an unmatched OPTIONAL MATCH yields {name: null}."""
        cc = _metadata_neighbor(
            _button_entry(),
            {NOTE_LIST_BUTTON_UID: {"props": [{"name": None, "isRequired": None}], "stateVars": []}},
        )
        assert cc.props == []


class TestBuildersThreadTheMap:
    PROPS = {NOTE_LIST_BUTTON_UID: NOTE_LIST_BUTTON_PROPS}

    def test_feature_addition_children(self, tmp_path):
        a = _Assembly(task_spec="", task_type="feature_addition", project_name="takenote")
        _build_feature_addition(
            a,
            [{"componentName": "NoteList", "filePath": "x.tsx", "children": [_button_entry()]}],
            [],
            [],
            tmp_path,
            self.PROPS,
        )
        assert a.neighbors[0][1].required_props == ["dataTestID", "handler"]

    def test_bug_fix_parents_and_consumers(self, tmp_path):
        a = _Assembly(task_spec="", task_type="bug_fix", project_name="takenote")
        _build_bug_fix(
            a,
            [{"componentName": "X", "filePath": "x.tsx", "directParents": [_button_entry()]}],
            tmp_path,
            self.PROPS,
        )
        assert a.neighbors[0][1].required_props == ["dataTestID", "handler"]

    def test_refactoring_callers(self, tmp_path):
        a = _Assembly(task_spec="", task_type="refactoring", project_name="takenote")
        _build_refactoring(
            a,
            [{"componentName": "X", "filePath": "x.tsx", "callers": [_button_entry()]}],
            tmp_path,
            {},
            self.PROPS,
        )
        assert a.neighbors[0][1].required_props == ["dataTestID", "handler"]


class TestBudgetLadder:
    """Richer neighbours must degrade gracefully rather than pushing the whole
    section off — but props are dropped only at the rung before the names go too,
    because a bare name-and-path is the defect this change exists to fix.
    """

    # The neighbour role each ladder keeps longest — the one whose props are the
    # last metadata standing before the section goes.
    LAST_ROLE = {"bug_fix": "used_by", "feature_addition": "child", "refactoring": "caller"}

    @classmethod
    def _assembly(cls, task_type: str) -> _Assembly:
        a = _Assembly(task_spec="", task_type=task_type, project_name="takenote")
        a.neighbors.append((
            cls.LAST_ROLE[task_type],
            _metadata_neighbor(_button_entry(), {NOTE_LIST_BUTTON_UID: NOTE_LIST_BUTTON_PROPS}),
        ))
        return a

    def test_props_counted_in_the_estimate(self):
        """Uncounted props would make truncation fire late — the budget would be
        silently exceeded by exactly the tokens this change adds."""
        with_props = self._assembly("feature_addition").estimate()
        bare = _Assembly(task_spec="", task_type="feature_addition", project_name="takenote")
        bare.neighbors.append(("child", _metadata_neighbor(_button_entry())))
        assert with_props > bare.estimate()

    def test_clear_props_keeps_names(self):
        a = self._assembly("feature_addition")
        _clear_neighbor_props(a)
        assert a.neighbors[0][1].name == "NoteListButton"
        assert a.neighbors[0][1].props == []

    def test_props_rung_precedes_the_neighbour_drop_for_every_task_type(self):
        for task_type in ("bug_fix", "feature_addition", "refactoring"):
            steps = _removal_steps(task_type)
            props_rung = next(
                i for i, s in enumerate(steps) if s is _clear_neighbor_props
            )
            a = self._assembly(task_type)
            # Applying every rung up to and including the props rung must leave
            # the neighbour present but bare.
            for step in steps[: props_rung + 1]:
                step(a)
            surviving = [cc for _r, cc in a.neighbors]
            assert all(cc.props == [] for cc in surviving), task_type
            # And a later rung must actually remove them.
            for step in steps[props_rung + 1 :]:
                step(a)
            assert a.neighbors == [], task_type


class TestRendering:
    def test_related_components_carries_the_required_prop(self):
        data = ContextData(
            task_spec="",
            task_type="feature_addition",
            target_components=[],
            neighbor_components=[
                _metadata_neighbor(
                    _button_entry(), {NOTE_LIST_BUTTON_UID: NOTE_LIST_BUTTON_PROPS}
                ).model_copy(update={"relation": "child"})
            ],
        )
        rendered = ContextRenderer().render("A", data)
        assert "- Props: dataTestID, handler, label" in rendered
        assert "- Required: dataTestID, handler" in rendered

    def test_no_blank_line_bleed(self):
        """Each false {% if %} used to emit a stray newline, so a neighbour with no
        metadata rendered as a heading followed by six to eight blank lines."""
        data = ContextData(
            task_spec="",
            task_type="feature_addition",
            target_components=[],
            neighbor_components=[
                ComponentContext(
                    name="SearchBar",
                    file_path="src/client/components/NoteList/SearchBar.tsx",
                    component_type="Function_Component",
                    relation="child",
                )
            ],
        )
        rendered = ContextRenderer().render("A", data)
        assert "\n\n\n" not in rendered.split("### Related Components")[1]


class TestRetrieverUidCollection:
    def test_collects_across_every_neighbour_field(self):
        rows = [
            {"children": [{"uid": "a"}], "callers": [{"uid": "b"}]},
            {"directParents": [{"uid": "c"}], "usedByComponents": [{"uid": "d"}]},
        ]
        assert KGAugmentedRetriever._neighbor_uids(rows) == ["a", "b", "c", "d"]

    def test_deduplicates(self):
        rows = [{"children": [{"uid": "a"}, {"uid": "a"}]}, {"callers": [{"uid": "a"}]}]
        assert KGAugmentedRetriever._neighbor_uids(rows) == ["a"]

    def test_derives_uid_when_the_template_omits_it(self):
        rows = [{"children": [_button_entry(with_uid=False)]}]
        assert KGAugmentedRetriever._neighbor_uids(rows) == [NOTE_LIST_BUTTON_UID]

    def test_tolerates_null_collect_placeholders(self):
        rows = [{"children": [{"name": None, "filePath": None, "uid": None}, None]}]
        assert KGAugmentedRetriever._neighbor_uids(rows) == []

    def test_empty_when_no_neighbours(self):
        """No neighbours means the companion query is skipped entirely."""
        assert KGAugmentedRetriever._neighbor_uids([{"componentName": "X"}]) == []


class TestAssembleContextEndToEnd:
    def test_props_reach_the_rendered_neighbour(self, tmp_path):
        data = assemble_context(
            task_spec="add a restore-all-trash button",
            task_type="feature_addition",
            rows=[{"componentName": "NoteList", "filePath": "x.tsx", "children": [_button_entry()]}],
            repo_root=tmp_path,
            project_name="takenote",
            neighbor_props={NOTE_LIST_BUTTON_UID: NOTE_LIST_BUTTON_PROPS},
        )
        assert data.neighbor_components[0].required_props == ["dataTestID", "handler"]

    def test_omitting_the_map_is_backward_compatible(self, tmp_path):
        data = assemble_context(
            task_spec="",
            task_type="feature_addition",
            rows=[{"componentName": "NoteList", "filePath": "x.tsx", "children": [_button_entry()]}],
            repo_root=tmp_path,
            project_name="takenote",
        )
        assert data.neighbor_components[0].props == []
