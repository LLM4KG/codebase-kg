# codebase-kg

A Python-based research pipeline built around a single hypothesis: that structured semantic knowledge encoded in a Knowledge Graph can give an LLM the *right context* for more reliable, consistent and accurate code generation. It comes in two phases.

**Phase 1 — Knowledge extraction (implemented).** Extracts Knowledge Graphs (KGs) from React.js codebases using LLMs and stores them in [Memgraph](https://memgraph.com/). Rather than AST parsing, few-shot LLM prompts read each source file directly and return validated JSON describing components, hooks, props, state, contexts and routes, which is ingested into an 11-node-type / 30-relationship schema and exported as a Git-committed CYPHERL snapshot.

**Phase 2 — KG-augmented code generation (in progress).** Uses those KGs at inference time: a task is classified, parameterised Cypher templates retrieve the relevant slice of the graph, and the result is rendered into the generator's prompt. A Docker-based evaluation harness applies each generated edit and runs the project's tests, so KG-augmented context can be compared against baseline conditions on real repair and feature tasks. Retrieval is deliberately template-heavy and agent-light; fully-agentic retrieval is left to future work.

---

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- Docker and Docker Compose
- An Anthropic (or OpenAI / Gemini) API key

---

## 1. Setup

**Clone and install dependencies:**

```bash
git clone <repo-url>
cd codebase-kg
uv sync
```

**Configure your API key:**

```bash
cp .env.example .env
# Edit .env and add your API key, e.g.:
# ANTHROPIC_API_KEY=sk-ant-...
```

**Start Memgraph:**

```bash
docker compose up -d
```

---

## 2. Run the Extraction Pipeline

Point the pipeline at a cloned React.js repository:

```bash
uv run pipeline extract --repo /path/to/your/react-project
```

To use a specific model:

```bash
uv run pipeline extract --repo /path/to/your/react-project --model anthropic/claude-sonnet-4-6
```

The default model and other settings can be changed in `pipeline.toml`.

---

## 3. Resume After an Error

The pipeline checkpoints progress per file. If it fails mid-run, you have two options:

**Resume from where it left off** (skips already-processed files, uses LLM cache):

```bash
uv run pipeline extract --repo /path/to/your/react-project
```

**Start completely fresh** (clears the checkpoint and reprocesses all files):

First wipe the graph database:

```bash
echo "MATCH (n) DETACH DELETE n;" | docker exec -i codebase-kg-memgraph-1 mgconsole
```

Then re-run with `--reset`:

```bash
uv run pipeline extract --repo /path/to/your/react-project --reset
```

> **Note:** `--reset` clears the checkpoint but keeps the LLM response cache. Add `rm -rf .cache/llm` before re-running only if you also want to force fresh LLM calls (e.g. after changing prompts).

---

## 4. View Pipeline Status

Check how many nodes and relationships are currently in the graph:

```bash
uv run pipeline status
```

---

## 5. Export the KG

Export the graph to a `.cypherl` file (one Cypher statement per line):

```bash
uv run pipeline export --output ./graph_export/<project-name>/
```

This produces:
- `full_dump.cypherl` — complete KG dump, suitable for re-import
- `manifest.json` — node and relationship counts

---

## 6. Add the Exported KG to Your Project's Git Repo

Copy the exported files into the target project and commit them:

```bash
mkdir -p /path/to/your/react-project/knowledge_graph

cp graph_export/<project-name>/full_dump.cypherl /path/to/your/react-project/knowledge_graph/
cp graph_export/<project-name>/manifest.json /path/to/your/react-project/knowledge_graph/

cd /path/to/your/react-project
git add knowledge_graph/
git commit -m "Add knowledge graph export"
```

The `.cypherl` file is plain text and fully diffable in Git.

---

## 7. Import a Project's KG into Memgraph

If you have a React project with a `knowledge_graph/` folder already committed, you can reconstruct the KG without running any LLM calls.

**Clear any existing graph first:**

```bash
echo "MATCH (n) DETACH DELETE n;" | docker exec -i codebase-kg-memgraph-1 mgconsole
```

**Then import:**

```bash
uv run pipeline import --input /path/to/your/react-project/knowledge_graph/full_dump.cypherl
```

---

## 8. Visualize the KG in Memgraph Lab

Open [http://localhost:3000](http://localhost:3000) in your browser. Click **Connect** (pre-filled with `localhost:7687`), then run a Cypher query in the **Query** tab and switch to the **Graph** view.

Example queries:

```cypher
-- All nodes and relationships (capped to avoid overload)
MATCH (n)-[r]->(m) RETURN n, r, m LIMIT 200;

-- All function components and their relationships
MATCH (n:Function_Component)-[r]->(m) RETURN n, r, m;

-- Everything in a specific file
MATCH (n)-[r]->(m) WHERE n.filePath = "src/App.jsx" RETURN n, r, m;
```
