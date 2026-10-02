"""WP7 scoring rules."""

import pytest

from src.evaluation.annotation import Endpoint, Header, Item, parse_annotation_file, render_annotation_file
from src.evaluation.scoring import Counts, aggregate, agreement, cause_of, causes, package_check, score_file

PATH = "src/App.tsx"
FC = Endpoint("Function_Component", "App", None, PATH)
BTN = Endpoint("Function_Component", "Button", None, "src/Button.tsx")
ITEMS = [
    Item("N", Endpoint("File", loc=PATH)),
    Item("N", FC),
    Item("N", Endpoint("Prop", "title", "App", PATH)),
    Item("E", FC, "USES_COMPONENT", BTN),
    Item("E", FC, "DEFINED_IN", Endpoint("File", loc=PATH)),
]


def annotate(verdicts=None, missed=(), status="done", items=ITEMS):
    header = Header("demo", PATH, "a" * 40, "ps", "g")
    text = render_annotation_file(header, "x\n", items, "tsx")
    for line, mark in (verdicts or {}).items():
        text = text.replace(f"- [ ] {line}", f"- [{mark}] {line}", 1)
    text = text.replace("- [ ] ", "- [y] ").replace("status: todo", f"status: {status}")
    text = text.replace("<!-- wp6:missed -->\n", "<!-- wp6:missed -->\n" + "".join(m + "\n" for m in missed))
    return parse_annotation_file(text)


def test_verdicts_become_tp_fp_unsure():
    fs = score_file(annotate({"N Prop:App::title": "n", "E USES_COMPONENT Function_Component:App -> "
                                                         "Function_Component:Button@src/Button.tsx": "?"}), ITEMS, "content")
    assert fs.scored
    assert len(fs.tp) == 3 and [i.type for i, _ in fs.fp] == ["Prop"] and [i.type for i, _ in fs.unsure] == ["USES_COMPONENT"]


def test_missed_items_are_fn_only_when_this_file_is_their_evidence_file():
    fs = score_file(annotate(missed=[
        "N State_Variable:App::open",                                              # FN
        "E USES_COMPONENT Function_Component:App -> Function_Component:Icon@src/Icon.tsx",  # FN
        "N Function_Component:Other@src/Other.tsx",                                 # defined elsewhere
        "E USES_COMPONENT Function_Component:Other@src/Other.tsx -> Function_Component:App",  # stated elsewhere
        "E IMPORTS File -> File@src/Button.tsx",                                    # not implemented
        "N Library:react",                                                           # package-level
        "N State_Variable:App::open",                                               # duplicate, ignored
    ]), ITEMS, "content")
    assert [i.text(PATH) for i, _ in fs.fn] == [
        "N State_Variable:App::open",
        "E USES_COMPONENT Function_Component:App -> Function_Component:Icon@src/Icon.tsx",
    ]
    assert len(fs.set_aside) == 4


def test_a_missed_item_that_was_pre_filled_is_a_conflict_not_an_fn():
    fs = score_file(annotate({"N Prop:App::title": "n"}, missed=["N Prop:App::title"]), ITEMS, "content")
    assert fs.fn == [] and len(fs.conflicts) == 1 and len(fs.fp) == 1


@pytest.mark.parametrize("kwargs, problem", [
    ({"status": "todo"}, "status"),
    ({"missed": ["N Prop:oops"]}, "Owner::name"),
])
def test_incomplete_or_malformed_files_are_not_scored(kwargs, problem):
    fs = score_file(annotate(**kwargs), ITEMS, "content")
    assert not fs.scored and any(problem in p for p in fs.problems)


def test_a_file_whose_prefill_differs_from_the_kg_is_not_scored():
    fs = score_file(annotate(), ITEMS[:-1], "content")    # KG now has one item fewer
    assert not fs.scored and any("differ from the KG" in p for p in fs.problems)


def test_aggregate_separates_scopes_and_micro_averages():
    fs = score_file(annotate({"N Prop:App::title": "n"}, missed=["N State_Variable:App::open"]), ITEMS, "content")
    agg = aggregate([fs])
    llm = agg[("llm", "all", "all", "*")]
    assert (llm.tp, llm.fp, llm.fn) == (3, 1, 1)                   # FC, USES_COMPONENT, DEFINED_IN
    assert (agg[("deterministic", "all", "all", "*")].tp) == 1      # File
    assert agg[("llm", "repo", "demo", "Prop")].fp == 1
    assert llm.precision == pytest.approx(0.75) and llm.recall == pytest.approx(0.75)


def test_unscored_files_contribute_nothing():
    fs = score_file(annotate(status="todo"), ITEMS, "content")
    assert aggregate([fs]) == {}


def test_counts_handle_empty_denominators():
    assert Counts().precision is None and Counts().f1 is None
    assert Counts(tp=0, fp=2).precision == 0.0 and Counts(tp=0, fp=2).f1 is None


def test_cause_tags():
    assert cause_of("cause: Resolution — wrong barrel") == "resolution"
    assert cause_of("looks odd") is None
    fs = score_file(annotate({"N Prop:App::title": "n"}), ITEMS, "content")
    fs.fp[0] = (fs.fp[0][0], "cause: llm")
    assert causes([fs])[("FP", "Prop", "llm")] == 1


def test_package_check_against_package_json():
    items = [
        Item("N", Endpoint("Project", "demo")),
        Item("N", Endpoint("Library", "react")),
        Item("N", Endpoint("Library", "left-pad")),
        Item("E", Endpoint("Project", "demo"), "DEPENDS_ON", Endpoint("Library", "react")),
    ]
    res = package_check(items, {"name": "demo", "dependencies": {"react": "18"}, "devDependencies": {"jest": "29"}})
    assert (res["Library"].tp, res["Library"].fp, res["Library"].fn) == (1, 1, 1)
    assert (res["DEPENDS_ON"].tp, res["DEPENDS_ON"].fn) == (1, 1)
    assert res["Project"].tp == 1


def test_agreement_kappa():
    a = score_file(annotate({"N Prop:App::title": "n"}), ITEMS, "content")
    b = score_file(annotate({"N Prop:App::title": "n", "N Function_Component:App": "n"}), ITEMS, "content")
    g = agreement(a, b)
    assert (g.items, g.agree) == (5, 4)
    # po = 0.8; pa_y = 0.8, pb_y = 0.6 -> pe = 0.56; kappa = 0.24 / 0.44
    assert g.kappa == pytest.approx(0.24 / 0.44)
    same = agreement(a, a)
    assert same.kappa == pytest.approx(1.0)
