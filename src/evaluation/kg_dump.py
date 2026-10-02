"""Read a committed `.cypherl` graph dump into nodes and edges — no Memgraph needed.

The dumps under `graph_export/<project>/full_dump.cypherl` are the graphs of record
(Memgraph's `DUMP DATABASE` format). Two statement shapes carry the data:

    CREATE (:__mg_vertex__:`Label` {__mg_id__: 7, `key`: "value", ...});
    MATCH (u:__mg_vertex__), (v:__mg_vertex__) WHERE u.__mg_id__ = 1 AND v.__mg_id__ = 7
        CREATE (u)-[:`REL` {`key`: "value"}]->(v);

Everything else (indexes, constraints, cleanup of the helper label) is ignored.
Property values are read as strings, numbers, booleans or null; lists are kept as
their raw text, since nothing here needs them.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

_NODE_RE = re.compile(r"^CREATE \(:__mg_vertex__:`(\w+)` \{__mg_id__: (\d+)(.*)\}\);$")
_EDGE_RE = re.compile(
    r"^MATCH \(u:__mg_vertex__\), \(v:__mg_vertex__\) WHERE u\.__mg_id__ = (\d+) "
    r"AND v\.__mg_id__ = (\d+) CREATE \(u\)-\[:`(\w+)`(?: \{(.*)\})?\]->\(v\);$"
)
# `key`: value — value is a JSON-style string, a number, a boolean, null, or a list.
_PROP_RE = re.compile(
    r"`(\w+)`: (\"(?:[^\"\\]|\\.)*\"|-?\d+(?:\.\d+)?|true|false|null|\[[^\]]*\])"
)


def _parse_props(text: str) -> dict:
    props: dict = {}
    for key, raw in _PROP_RE.findall(text or ""):
        if raw.startswith('"'):
            # Memgraph escapes single quotes as \', which JSON does not allow.
            props[key] = json.loads(raw.replace("\\'", "'"))
        elif raw in ("true", "false"):
            props[key] = raw == "true"
        elif raw == "null":
            props[key] = None
        elif raw.startswith("["):
            props[key] = raw
        else:
            props[key] = float(raw) if "." in raw else int(raw)
    return props


@dataclass(frozen=True)
class Node:
    id: int
    label: str
    props: dict = field(hash=False, compare=False)

    @property
    def file_path(self) -> str | None:
        return self.props.get("filePath")


@dataclass(frozen=True)
class Edge:
    src: int
    dst: int
    type: str
    props: dict = field(hash=False, compare=False)


@dataclass
class Graph:
    nodes: dict[int, Node]
    edges: list[Edge]

    def files(self) -> list[str]:
        """Repo-relative paths of every `File` node, sorted."""
        return sorted(n.props["filePath"] for n in self.nodes.values() if n.label == "File")


def load_dump(path: str | Path) -> Graph:
    nodes: dict[int, Node] = {}
    edges: list[Edge] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            m = _NODE_RE.match(line)
            if m:
                node_id = int(m.group(2))
                nodes[node_id] = Node(node_id, m.group(1), _parse_props(m.group(3)))
                continue
            m = _EDGE_RE.match(line)
            if m:
                edges.append(Edge(int(m.group(1)), int(m.group(2)), m.group(3), _parse_props(m.group(4))))
    return Graph(nodes, edges)
