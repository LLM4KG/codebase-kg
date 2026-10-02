"""WP7 scoring: extraction precision / recall / F1 from the WP6 annotation files.

Rules (plan: docs/phase_2/ijckg-2026/wp6_annotation_plan.md; annotator guide:
docs/phase_2/ijckg-2026/annotation_guide.md):

- Only **complete** files are scored: `status: done`, every item decided, no syntax
  errors. Others are listed with what is missing, so coverage is stated, not hidden.
- A file's pre-filled items must equal the KG's items for that file (the graph of
  record). A mismatch means the file is stale or was edited; the file is not scored.
- `[y]` = TP, `[n]` = FP, `[?]` = unsure (reported, in neither P nor R).
- Step-3 items are FN, after checks:
  - an item must have this file as its evidence file (a node defined here; an edge
    whose source endpoint is here), or it is set aside as out of scope;
  - `IMPORTS` (never implemented) and package-level types are set aside;
  - an item that is also a pre-filled item is a conflict (marked `[n]`, yet listed
    as missing; or listed as missing although pre-filled): reported, not counted.
- `# cause: llm|resolution|schema` notes are counted per type, for error attribution.
- Two scopes, never mixed: the LLM-extracted headline, and the deterministic
  sanity scope. `Project` / `Library` / `DEPENDS_ON` are checked against
  `package.json` by `package_check`.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from src.evaluation.annotation import (
    EXCLUDED_RELS,
    FILE_SCOPED_LABELS,
    PACKAGE_LABELS,
    PACKAGE_RELS,
    Item,
    ParsedAnnotation,
)

_CAUSE_RE = re.compile(r"cause:\s*([a-z_]+)", re.I)


def cause_of(note: str | None) -> str | None:
    m = _CAUSE_RE.search(note or "")
    return m.group(1).lower() if m else None


@dataclass
class FileScore:
    project: str
    path: str
    stratum: str
    complete: bool
    status: str
    problems: list[str] = field(default_factory=list)
    tp: list[Item] = field(default_factory=list)
    fp: list[tuple[Item, str | None]] = field(default_factory=list)
    unsure: list[tuple[Item, str | None]] = field(default_factory=list)
    fn: list[tuple[Item, str | None]] = field(default_factory=list)
    set_aside: list[tuple[Item, str]] = field(default_factory=list)
    conflicts: list[tuple[Item, str]] = field(default_factory=list)

    @property
    def scored(self) -> bool:
        return self.complete and not self.problems


def _evidence_ok(item: Item, path: str) -> str | None:
    """None if `path` is the item's evidence file, else the reason it is not."""
    if item.kind == "N":
        if item.src.label in PACKAGE_LABELS or item.src.label == "Library_Hook":
            return "package-level or global node; not annotated per file"
        return None if item.src.loc == path else f"node defined in {item.src.loc}"
    if item.rel in EXCLUDED_RELS:
        return f"{item.rel} is not implemented by the pipeline"
    if item.rel in PACKAGE_RELS:
        return "package-level edge; checked against package.json"
    if item.rel == "PROVIDED_BY":
        return None
    if item.src.label in FILE_SCOPED_LABELS:
        return None if item.src.loc == path else f"edge stated in {item.src.loc} (its source's file)"
    return f"source {item.src.label} has no file"


def score_file(parsed: ParsedAnnotation, kg_items: list[Item], stratum: str) -> FileScore:
    fs = FileScore(parsed.project, parsed.path, stratum, parsed.complete, parsed.status)
    if parsed.status != "done":
        fs.problems.append(f"status is {parsed.status!r}")
    if parsed.undecided:
        fs.problems.append(f"{len(parsed.undecided)} undecided items")
    fs.problems += parsed.errors

    decided = {i: (v, note) for i, v, note in parsed.decisions}
    kg = set(kg_items)
    if set(decided) != kg:
        missing, extra = kg - set(decided), set(decided) - kg
        fs.problems.append(
            f"pre-filled items differ from the KG ({len(missing)} missing, {len(extra)} extra): "
            "stale or edited file"
        )

    for item, (verdict, note) in decided.items():
        if verdict == "correct":
            fs.tp.append(item)
        elif verdict == "wrong":
            fs.fp.append((item, note))
        elif verdict == "unsure":
            fs.unsure.append((item, note))

    seen: set[Item] = set()
    for item, note in parsed.missed:
        if item in seen:
            continue
        seen.add(item)
        if item in decided:
            verdict = decided[item][0]
            fs.conflicts.append((item, f"listed as missed but pre-filled and marked {verdict}"))
            continue
        reason = _evidence_ok(item, parsed.path)
        if reason:
            fs.set_aside.append((item, reason))
        else:
            fs.fn.append((item, note))
    return fs


# --------------------------------------------------------------------------- #
# Aggregation                                                                 #
# --------------------------------------------------------------------------- #
@dataclass
class Counts:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    unsure: int = 0

    @property
    def precision(self) -> float | None:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else None

    @property
    def recall(self) -> float | None:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else None

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.recall
        if p is None or r is None or p + r == 0:
            return None
        return 2 * p * r / (p + r)


def aggregate(files: list[FileScore]) -> dict[tuple, Counts]:
    """Counts keyed by (scope, group_kind, group, type), over scored files only.

    group_kind is "all", "repo" or "stratum"; type is a node/relationship type or
    "*" for the micro-average over the scope.
    """
    out: dict[tuple, Counts] = defaultdict(Counts)

    def bump(item: Item, attr: str, fs: FileScore) -> None:
        for gk, g in (("all", "all"), ("repo", fs.project), ("stratum", fs.stratum)):
            for t in (item.type, "*"):
                c = out[(item.scope, gk, g, t)]
                setattr(c, attr, getattr(c, attr) + 1)

    for fs in files:
        if not fs.scored:
            continue
        for i in fs.tp:
            bump(i, "tp", fs)
        for i, _ in fs.fp:
            bump(i, "fp", fs)
        for i, _ in fs.fn:
            bump(i, "fn", fs)
        for i, _ in fs.unsure:
            bump(i, "unsure", fs)
    return out


def causes(files: list[FileScore]) -> Counter:
    """(error kind, type, cause) -> count, over scored files. cause None = not tagged."""
    c: Counter = Counter()
    for fs in files:
        if not fs.scored:
            continue
        for i, note in fs.fp:
            c[("FP", i.type, cause_of(note))] += 1
        for i, note in fs.fn:
            c[("FN", i.type, cause_of(note))] += 1
    return c


# --------------------------------------------------------------------------- #
# Package-level check (deterministic scope)                                   #
# --------------------------------------------------------------------------- #
def package_check(package_items: list[Item], package_json: dict) -> dict[str, Counts]:
    """Project / Library / DEPENDS_ON in the KG against package.json.

    The extractor takes `dependencies` + `devDependencies`; a package in both is
    one library. Expected to be perfect: this is the sanity scope.
    """
    deps = set(package_json.get("dependencies") or {}) | set(package_json.get("devDependencies") or {})
    kg_libs = {i.src.name for i in package_items if i.kind == "N" and i.src.label == "Library"}
    kg_dep_edges = {i.dst.name for i in package_items if i.kind == "E" and i.rel == "DEPENDS_ON"}
    projects = [i.src.name for i in package_items if i.kind == "N" and i.src.label == "Project"]
    expected_name = package_json.get("name")

    def counts(kg: set, truth: set) -> Counts:
        return Counts(tp=len(kg & truth), fp=len(kg - truth), fn=len(truth - kg))

    proj = Counts()
    for name in projects:
        if expected_name is None or name == expected_name:
            proj.tp += 1
        else:
            proj.fp += 1
    if not projects:
        proj.fn = 1
    return {"Project": proj, "Library": counts(kg_libs, deps), "DEPENDS_ON": counts(kg_dep_edges, deps)}


# --------------------------------------------------------------------------- #
# Inter-annotator agreement                                                   #
# --------------------------------------------------------------------------- #
@dataclass
class Agreement:
    items: int
    agree: int
    kappa: float | None
    missed_a: int
    missed_b: int
    missed_both: int


def agreement(a: FileScore, b: FileScore) -> Agreement:
    """Agreement on pre-filled verdicts (y/n only) and overlap of missed items."""
    va = {i: "y" for i in a.tp} | {i: "n" for i, _ in a.fp}
    vb = {i: "y" for i in b.tp} | {i: "n" for i, _ in b.fp}
    common = sorted(set(va) & set(vb))
    agree = sum(va[i] == vb[i] for i in common)
    kappa = None
    if common:
        n = len(common)
        po = agree / n
        pa_y = sum(va[i] == "y" for i in common) / n
        pb_y = sum(vb[i] == "y" for i in common) / n
        pe = pa_y * pb_y + (1 - pa_y) * (1 - pb_y)
        kappa = 1.0 if pe == 1 else (po - pe) / (1 - pe)
    ma, mb = {i for i, _ in a.fn}, {i for i, _ in b.fn}
    return Agreement(len(common), agree, kappa, len(ma), len(mb), len(ma & mb))
