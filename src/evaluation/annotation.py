"""WP6 annotation set: item identities, evidence files, file format, parser, sampling.

Design and rationale: `docs/phase_2/ijckg-2026/wp6_annotation_plan.md`.
Annotator-facing rules: `docs/phase_2/ijckg-2026/annotation_guide.md`.

**Items.** One node or edge of the KG, in one line of text:

    N Function_Component:CategoryList
    N Prop:Button::onClick
    E PASSES_PROP Function_Component:CategoryList -> Function_Component:AddCategoryForm@src/x.tsx prop=submitHandler
    E USES_LIBRARY_HOOK Function_Component:CategoryList -> Library_Hook:useState@react

An endpoint is `Label[:name][@loc]`. `loc` is a repo-relative path for
file-scoped labels (default: the annotation file's own path), the hook's source
for `Library_Hook`, and absent for `Library` / `Project`. Owned labels (`Prop`,
`State_Variable`, `EventHandler`) are named `Owner::name`, with the `uid`'s own
separator: both parts can contain dots (`Form.Field::name`, `ConfirmModal::modal.close`).
`PASSES_PROP` and `ROUTES_TO` carry `prop=` / `path=`, which distinguish
multi-edges and so are identity, not attributes.

**Evidence file.** Each item is annotated in the one file whose code states it:
a node in its own file; an edge in its *source* endpoint's file (for a `File`
source, that file); a `PROVIDED_BY` edge in every file that uses the hook.
`Project` / `Library` / `DEPENDS_ON` have no evidence file: they are package-level
and checked against `package.json` by the WP7 scorer.
"""

from __future__ import annotations

import random
import re
import shlex
from collections import defaultdict
from dataclasses import dataclass, field

from src.evaluation.kg_dump import Graph, Node

OWNED_LABELS = frozenset({"Prop", "State_Variable", "EventHandler"})
FILE_SCOPED_LABELS = frozenset(
    {"File", "Function_Component", "Class_Component", "Custom_Hook", "Context"} | OWNED_LABELS
)
DETERMINISTIC_LABELS = frozenset({"Project", "File", "Library"})
DETERMINISTIC_RELS = frozenset({"BELONGS_TO", "DEPENDS_ON", "PROVIDED_BY"})
# Package-level: no evidence file; WP7 checks them programmatically.
PACKAGE_LABELS = frozenset({"Project", "Library"})
PACKAGE_RELS = frozenset({"DEPENDS_ON"})
# In the schema but never created by the pipeline — reported, not annotated.
EXCLUDED_RELS = frozenset({"IMPORTS"})
# Edge property that is part of the edge's identity -> the key used in the text form.
EDGE_KEYS = {"PASSES_PROP": ("propName", "prop"), "ROUTES_TO": ("path", "path")}

NODE_ORDER = [
    "File", "Function_Component", "Class_Component", "Custom_Hook", "Context",
    "Prop", "State_Variable", "EventHandler", "Library_Hook", "Library", "Project",
]
VERDICTS = {"y": "correct", "x": "correct", "n": "wrong", "?": "unsure", " ": "undecided"}

MARK = {
    "notes": ("<!-- wp6:notes -->", "<!-- wp6:notes-end -->"),
    "items": ("<!-- wp6:items -->", "<!-- wp6:items-end -->"),
    "missed": ("<!-- wp6:missed -->", "<!-- wp6:missed-end -->"),
}


# --------------------------------------------------------------------------- #
# Identities                                                                  #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, order=True)
class Endpoint:
    label: str
    name: str | None = None
    owner: str | None = None
    loc: str | None = None

    def text(self, this_file: str | None = None) -> str:
        out = self.label
        if self.name is not None:
            out += ":" + (f"{self.owner}::{self.name}" if self.owner is not None else self.name)
        if self.loc is not None and not (self.label in FILE_SCOPED_LABELS and self.loc == this_file):
            out += "@" + self.loc
        return out


@dataclass(frozen=True, order=True)
class Item:
    kind: str                    # "N" or "E"
    src: Endpoint                # the node, for "N"
    rel: str | None = None
    dst: Endpoint | None = None
    key: tuple[str, str] | None = None   # ("prop", "submitHandler") / ("path", "/food")

    @property
    def type(self) -> str:
        return self.src.label if self.kind == "N" else self.rel

    @property
    def scope(self) -> str:
        if self.kind == "N":
            return "deterministic" if self.src.label in DETERMINISTIC_LABELS else "llm"
        return "deterministic" if self.rel in DETERMINISTIC_RELS else "llm"

    def text(self, this_file: str | None = None) -> str:
        if self.kind == "N":
            return f"N {self.src.text(this_file)}"
        out = f"E {self.rel} {self.src.text(this_file)} -> {self.dst.text(this_file)}"
        if self.key is not None:
            out += f" {self.key[0]}={shlex.quote(self.key[1])}"
        return out


def node_endpoint(node: Node) -> Endpoint:
    p = node.props
    if node.label == "File":
        return Endpoint("File", loc=p["filePath"])
    if node.label in OWNED_LABELS:
        return Endpoint(node.label, p["name"], p.get("componentName"), p.get("filePath"))
    if node.label in FILE_SCOPED_LABELS:
        return Endpoint(node.label, p["name"], None, p.get("filePath"))
    if node.label == "Library_Hook":
        return Endpoint("Library_Hook", p["name"], None, p.get("source"))
    return Endpoint(node.label, p.get("name"))


def _endpoint_file(ep: Endpoint) -> str | None:
    return ep.loc if ep.label in FILE_SCOPED_LABELS else None


# --------------------------------------------------------------------------- #
# Graph -> items per evidence file                                            #
# --------------------------------------------------------------------------- #
@dataclass
class ItemSet:
    by_file: dict[str, list[Item]]
    package: list[Item]              # Project / Library / DEPENDS_ON (programmatic check)
    excluded: list[Item] = field(default_factory=list)   # IMPORTS, if it ever appears


def items_by_evidence_file(graph: Graph) -> ItemSet:
    by_file: dict[str, set[Item]] = defaultdict(set)
    package: set[Item] = set()
    excluded: set[Item] = set()
    for f in graph.files():
        by_file[f]  # every file gets an entry, even with no items beyond its File node

    for node in graph.nodes.values():
        ep = node_endpoint(node)
        item = Item("N", ep)
        if node.label in PACKAGE_LABELS:
            package.add(item)
        elif node.label == "Library_Hook":
            continue  # global; scored through its edges
        else:
            by_file[_endpoint_file(ep)].add(item)

    hook_users: dict[int, set[str]] = defaultdict(set)
    for e in graph.edges:
        if e.type == "USES_LIBRARY_HOOK":
            f = graph.nodes[e.src].file_path
            if f:
                hook_users[e.dst].add(f)

    for e in graph.edges:
        src, dst = graph.nodes[e.src], graph.nodes[e.dst]
        key = None
        if e.type in EDGE_KEYS:
            prop, short = EDGE_KEYS[e.type]
            key = (short, str(e.props.get(prop)))
        item = Item("E", node_endpoint(src), e.type, node_endpoint(dst), key)
        if e.type in EXCLUDED_RELS:
            excluded.add(item)
        elif e.type in PACKAGE_RELS:
            package.add(item)
        elif e.type == "PROVIDED_BY":
            for f in hook_users.get(e.src, ()):
                by_file[f].add(item)
        else:
            f = _endpoint_file(item.src)
            if f is None:
                raise ValueError(f"No evidence file for {item.text()}")
            by_file[f].add(item)

    return ItemSet(
        {f: sort_items(items) for f, items in sorted(by_file.items())},
        sort_items(package),
        sort_items(excluded),
    )


def sort_items(items) -> list[Item]:
    def k(it: Item):
        rank = NODE_ORDER.index(it.src.label) if it.src.label in NODE_ORDER else 99
        return (it.kind != "N", it.rel or "", rank, it.src, it.dst or Endpoint(""), it.key or ("", ""))
    return sorted(items, key=k)


def coverage_types(items: list[Item]) -> set[str]:
    """In-scope node and relationship types a file is evidence for.

    `File` and `BELONGS_TO` are in every file, so they cannot steer sampling.
    `Library_Hook` is covered wherever a hook is used.
    """
    types = set()
    for it in items:
        if it.type in ("File", "BELONGS_TO"):
            continue
        types.add(it.type)
        if it.kind == "E" and it.dst is not None and it.dst.label == "Library_Hook":
            types.add("Library_Hook")
    return types


# --------------------------------------------------------------------------- #
# Parsing item lines                                                          #
# --------------------------------------------------------------------------- #
class ItemSyntaxError(ValueError):
    pass


_ENDPOINT_RE = re.compile(r"^([A-Za-z_]+)(?::([^@\s]+))?(?:@(\S+))?$")


def parse_endpoint(text: str, this_file: str) -> Endpoint:
    m = _ENDPOINT_RE.match(text)
    if not m:
        raise ItemSyntaxError(f"bad endpoint {text!r}")
    label, name, loc = m.groups()
    if label not in NODE_ORDER:
        raise ItemSyntaxError(f"unknown node type {label!r}")
    if label == "File":
        if name is not None:
            raise ItemSyntaxError("File takes no name; use File or File@path")
        return Endpoint("File", loc=loc or this_file)
    if name is None:
        raise ItemSyntaxError(f"{label} needs a name: {label}:<name>")
    owner = None
    if label in OWNED_LABELS:
        if "::" not in name:
            raise ItemSyntaxError(f"{label} is named Owner::name, got {name!r}")
        owner, name = name.split("::", 1)
    if label in FILE_SCOPED_LABELS:
        return Endpoint(label, name, owner, loc or this_file)
    if label == "Library_Hook":
        if loc is None:
            raise ItemSyntaxError("Library_Hook needs its source: Library_Hook:useState@react")
        return Endpoint(label, name, None, loc)
    if loc is not None:
        raise ItemSyntaxError(f"{label} takes no @location")
    return Endpoint(label, name)


def parse_item(text: str, this_file: str) -> Item:
    try:
        tokens = shlex.split(text)
    except ValueError as exc:
        raise ItemSyntaxError(str(exc)) from exc
    if not tokens or tokens[0] not in ("N", "E"):
        raise ItemSyntaxError("an item starts with N (node) or E (edge)")
    if tokens[0] == "N":
        if len(tokens) != 2:
            raise ItemSyntaxError("a node is: N Label:name[@path]")
        return Item("N", parse_endpoint(tokens[1], this_file))
    if len(tokens) not in (5, 6) or tokens[3] != "->":
        raise ItemSyntaxError("an edge is: E REL Source -> Target [prop=…|path=…]")
    rel = tokens[1]
    if not re.fullmatch(r"[A-Z_]+", rel):
        raise ItemSyntaxError(f"bad relationship type {rel!r}")
    src, dst = parse_endpoint(tokens[2], this_file), parse_endpoint(tokens[4], this_file)
    key = None
    if rel in EDGE_KEYS:
        want = EDGE_KEYS[rel][1]
        if len(tokens) != 6 or not tokens[5].startswith(want + "="):
            raise ItemSyntaxError(f"{rel} needs {want}=<value>")
        key = (want, tokens[5][len(want) + 1:])
    elif len(tokens) == 6:
        raise ItemSyntaxError(f"{rel} takes no key")
    return Item("E", src, rel, dst, key)


def _split_note(line: str) -> tuple[str, str | None]:
    # A note starts at " # "; item text itself never contains that sequence.
    if " # " in line:
        body, note = line.split(" # ", 1)
        return body.rstrip(), note.strip()
    return line, None


# --------------------------------------------------------------------------- #
# Annotation file: render and parse                                           #
# --------------------------------------------------------------------------- #
@dataclass
class Header:
    project: str
    path: str
    sha: str
    prompt_set: str
    graph: str


def render_annotation_file(header: Header, source: str, items: list[Item], lang: str) -> str:
    llm_nodes = [i for i in items if i.scope == "llm" and i.kind == "N"]
    llm_edges = [i for i in items if i.scope == "llm" and i.kind == "E"]
    det = [i for i in items if i.scope == "deterministic"]
    width = len(str(source.count("\n") + 1))
    numbered = "\n".join(f"{n:>{width}}  {line}" for n, line in enumerate(source.splitlines(), 1))

    def block(title: str, group: list[Item]) -> list[str]:
        out = [f"### {title} ({len(group)})", ""]
        out += [f"- [ ] {i.text(header.path)}" for i in group] or ["(none)"]
        return out + [""]

    lines = [
        f"# WP6 annotation — {header.project} · `{header.path}`",
        "",
        f"<!-- wp6 v1 project={header.project} path={header.path} sha={header.sha} "
        f"graph={header.graph} prompt_set={header.prompt_set} -->",
        "",
        "status: todo",
        "annotator:",
        "",
        "> Guide: `docs/phase_2/ijckg-2026/annotation_guide.md`. Work top to bottom and **finish",
        "> step 1 before you read step 2**. Set `status:` to `done` when the file is finished.",
        "",
        "## Step 1 — Read the source, then note what you see (not scored)",
        "",
        "List the components, hooks, props, state, handlers, contexts and routes you find, and",
        "what each component renders and uses. Do this *before* looking at step 2.",
        "",
        MARK["notes"][0],
        "",
        MARK["notes"][1],
        "",
        f"Source at `{header.sha[:7]}`:",
        "",
        f"````{lang}",
        numbered,
        "````",
        "",
        "## Step 2 — Review what the extractor found",
        "",
        "Set every `[ ]` to `[y]` (correct), `[n]` (wrong) or `[?]` (unsure). An item that is",
        "right but points at the wrong target is `[n]`; add the right one in step 3. Add",
        "` # cause: resolution|llm|schema` or any note after an item if useful.",
        "",
        MARK["items"][0],
        "",
        *block("LLM-extracted nodes", llm_nodes),
        *block("LLM-extracted edges", llm_edges),
        *block("Deterministic (sanity scope)", det),
        MARK["items"][1],
        "",
        "## Step 3 — What the extractor missed",
        "",
        "One item per line, in the step-2 syntax, without the checkbox. `@path` defaults to this",
        "file. Examples:",
        "",
        "    N Prop:Button::onClick",
        "    E USES_COMPONENT Function_Component:App -> Function_Component:Header@src/Header.tsx",
        "",
        MARK["missed"][0],
        "",
        MARK["missed"][1],
        "",
    ]
    return "\n".join(lines)


@dataclass
class ParsedAnnotation:
    project: str
    path: str
    status: str
    annotator: str
    decisions: list[tuple[Item, str, str | None]]   # (item, verdict, note)
    missed: list[tuple[Item, str | None]]
    errors: list[str]

    @property
    def undecided(self) -> list[Item]:
        return [i for i, v, _ in self.decisions if v == "undecided"]

    @property
    def complete(self) -> bool:
        return self.status == "done" and not self.undecided and not self.errors


_HEADER_RE = re.compile(r"<!-- wp6 v1 project=(\S+) path=(\S+) ")
_DECISION_RE = re.compile(r"^- \[(.)\] (.*)$")


def _section(lines: list[str], name: str) -> list[tuple[int, str]]:
    start, end = MARK[name]
    try:
        a, b = lines.index(start), lines.index(end)
    except ValueError as exc:
        raise ItemSyntaxError(f"section markers for {name!r} are missing") from exc
    return [(n + 1, lines[n]) for n in range(a + 1, b)]


def parse_annotation_file(text: str) -> ParsedAnnotation:
    lines = text.splitlines()
    head = next((m for m in map(_HEADER_RE.search, lines) if m), None)
    if head is None:
        raise ItemSyntaxError("missing the '<!-- wp6 v1 ... -->' header")
    project, path = head.groups()
    status = next((l.split(":", 1)[1].strip() for l in lines if l.startswith("status:")), "")
    annotator = next((l.split(":", 1)[1].strip() for l in lines if l.startswith("annotator:")), "")

    decisions, missed, errors = [], [], []
    for n, line in _section(lines, "items"):
        m = _DECISION_RE.match(line.strip())
        if not m:
            continue  # headings, blank lines, "(none)"
        mark, rest = m.group(1).lower(), m.group(2)
        body, note = _split_note(rest)
        if mark not in VERDICTS:
            errors.append(f"line {n}: verdict [{m.group(1)}] is not y, n or ?")
            continue
        try:
            decisions.append((parse_item(body, path), VERDICTS[mark], note))
        except ItemSyntaxError as exc:
            errors.append(f"line {n}: {exc}")
    for n, line in _section(lines, "missed"):
        s = line.strip()
        if not s or s.startswith(("<!--", ">", "#")):
            continue
        if s.startswith("- "):
            s = s[2:]
        body, note = _split_note(s)
        try:
            missed.append((parse_item(body, path), note))
        except ItemSyntaxError as exc:
            errors.append(f"line {n}: {exc}")
    return ParsedAnnotation(project, path, status, annotator, decisions, missed, errors)


# --------------------------------------------------------------------------- #
# Sampling                                                                    #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Pick:
    project: str
    path: str
    reason: str


def sample_files(
    types_by_file: dict[str, dict[str, set[str]]],
    quotas: dict[str, int],
    seed: int,
    project_order: list[str],
    empty_files: dict[str, set[str]] | None = None,
    empty_per_project: int = 0,
) -> list[Pick]:
    """Coverage pass (rarest type first) then stratified fill; deterministic for a seed.

    `types_by_file[project][path]` is the set of in-scope types that file is
    evidence for. The fill takes `empty_per_project` files per project from
    `empty_files[project]` (files with no LLM-extracted items, so whole-file
    misses are measured) and the rest uniformly from the other files. Returns
    picks ordered project by project (`project_order`), then by path.
    """
    empty_files = empty_files or {}
    rng = random.Random(seed)
    left = dict(quotas)
    chosen: dict[tuple[str, str], str] = {}
    covered: set[str] = set()

    file_count: dict[str, int] = defaultdict(int)
    for proj in project_order:
        for types in types_by_file[proj].values():
            for t in types:
                file_count[t] += 1

    for t in sorted(file_count, key=lambda t: (file_count[t], t)):
        if t in covered:
            continue
        candidates = sorted(
            (proj, path)
            for proj in project_order if left[proj] > 0
            for path, types in types_by_file[proj].items()
            if t in types and (proj, path) not in chosen
        )
        if not candidates:
            continue  # recorded as uncovered by the caller
        proj, path = rng.choice(candidates)
        chosen[(proj, path)] = f"covers {t}"
        left[proj] -= 1
        covered |= types_by_file[proj][path]

    for proj in project_order:
        empty = empty_files.get(proj, set())
        pool = sorted(p for p in empty if (proj, p) not in chosen)
        for path in rng.sample(pool, min(empty_per_project, left[proj], len(pool))):
            chosen[(proj, path)] = "fill: no LLM items"
            left[proj] -= 1
        pool = sorted(p for p in types_by_file[proj] if (proj, p) not in chosen and p not in empty)
        for path in rng.sample(pool, min(left[proj], len(pool))):
            chosen[(proj, path)] = "fill"
        left[proj] = 0

    return [
        Pick(proj, path, chosen[(proj, path)])
        for proj in project_order
        for path in sorted(p for (pr, p) in chosen if pr == proj)
    ]
