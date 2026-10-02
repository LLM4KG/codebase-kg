#!/usr/bin/env python3
"""Generate Tables 2 and 3 of the IJCKG 2026 camera-ready paper from committed artifacts.

Usage:  python camera_ready_tables.py <repo_root> [out.md]

Reads (never writes) these files under <repo_root>:
  docs/phase_2/ijckg-2026/wp7_extraction_accuracy.csv   Table 2 scores (scope=llm)
  docs/phase_2/ijckg-2026/wp7_extraction_accuracy.md    files scored / sampled per repo
  graph_export/<repo>/manifest.json                     source-file count per repo
  docs/phase_2/ijckg-2026/wp5_outcomes.csv              Table 3, 7,000-token view
  docs/phase_2/ijckg-2026/wp12_matched.csv              Table 3, budget-matched view
  docs/phase_2/ijckg-2026/wp12_per_edit_replay.csv      Table 3 footnote (anomaly A)

Every printed number comes from those files. The script also runs consistency checks
and exits non-zero if any fails, so a table that disagrees with its source is not produced.
"""
import csv
import json
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2]) if len(sys.argv) > 2 else None
D = root / "docs/phase_2/ijckg-2026"
failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


def rows(name):
    with open(D / name, newline="") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------- Table 2
REPOS = [  # (key in CSV / graph_export, display name), smallest to largest
    ("SnapShot", "SnapShot"),
    ("todoist", "Todoist Clone"),
    ("react-shopping-cart", "react-shopping-cart"),
    ("takenote", "TakeNote"),
    ("jira_clone", "Jira Clone (client)"),
]
acc = {(r["group_kind"], r["group"]): r for r in rows("wp7_extraction_accuracy.csv")
       if r["scope"] == "llm" and r["type"] == "*"}

sampled = {}
for line in (D / "wp7_extraction_accuracy.md").read_text().splitlines():
    m = re.match(r"\|\s*([\w\-]+)\s*\|\s*(\d+)\s*/\s*(\d+)", line)
    if m:
        sampled[m.group(1)] = (int(m.group(2)), int(m.group(3)))

t2 = ["| Repository | Source files | Files annotated | TP | FP | FN | P | R | F1 |",
      "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
tot = defaultdict(int)
for key, label in REPOS:
    r = acc[("repo", key)]
    files = json.loads((root / "graph_export" / key / "manifest.json").read_text())["provenance"]["file_count"]
    scored, of = sampled[key]
    check(scored == of, f"{key}: only {scored}/{of} sampled files scored")
    for k in ("tp", "fp", "fn"):
        tot[k] += int(r[k])
    tot["files"] += files
    tot["scored"] += scored
    t2.append(f"| {label} | {files} | {scored} | {r['tp']} | {r['fp']} | {r['fn']} | "
              f"{r['precision']} | {r['recall']} | {r['f1']} |")
a = acc[("all", "all")]
for k in ("tp", "fp", "fn"):
    check(tot[k] == int(a[k]), f"Table 2: repo {k} sum {tot[k]} != all-row {a[k]}")
t2.append(f"| **Micro-average** | **{tot['files']}** | **{tot['scored']}** | **{a['tp']}** | **{a['fp']}** | "
          f"**{a['fn']}** | **{a['precision']}** | **{a['recall']}** | **{a['f1']}** |")

# ---------------------------------------------------------------- Table 3
MODELS = ["Claude Sonnet 4.6", "Qwen3-Coder"]
TASKS = ["P1", "P2", "P3", "P4", "P5", "P6"]
wp5 = rows("wp5_outcomes.csv")
wp12 = rows("wp12_matched.csv")

# (row label, source rows, condition id)
ROWS = [
    ("No context (floor)", wp5, "floor"),
    ("Whole-file oracle (uncapped)", wp5, "whole_file"),
    ("**KG-augmented**", wp5, "kg_augmented"),
    ("BM25 @ 7,000 tokens", wp5, "bm25"),
    ("Dense @ 7,000 tokens", wp5, "text_emb_3_large"),
    ("BM25 @ KG's budget", wp12, "bm25_matched"),
    ("Dense @ KG's budget", wp12, "text_emb_3_large_matched"),
]


def cell(src, model, cond):
    got = {r["task"]: r for r in src if r["model"] == model and r["condition"] == cond}
    check(sorted(got) == TASKS, f"{model}/{cond}: tasks {sorted(got)}")
    return got


# Cross-check: the published rows repeated in wp12_matched.csv must equal wp5.
for model in MODELS:
    for cond in ("bm25", "text_emb_3_large", "kg_augmented"):
        a5 = cell(wp5, model, cond)
        a12 = {r["task"]: r for r in wp12
               if r["model"] == model and r["condition"] == cond and r["view"] == "published"}
        for t in TASKS:
            check(a5[t]["passed"] == a12[t]["passed"],
                  f"{model}/{cond}/{t}: wp5 passed {a5[t]['passed']} != wp12 {a12[t]['passed']}")

# Anomaly A: per-edit replay passes, added to the published count.
replay = defaultdict(int)
for r in rows("wp12_per_edit_replay.csv"):
    if r["replay_outcome"] == "passed":
        replay[(r["model_label"], r["condition"])] += 1

t3 = ["| Condition | Context tokens per task (range) | Median across 6 tasks | Claude Sonnet 4.6 | Qwen3-Coder |",
      "|---|---:|---:|---:|---:|"]
notes = []
for label, src, cond in ROWS:
    passed, toks = {}, {}
    for model in MODELS:
        c = cell(src, model, cond)
        passed[model] = sum(int(c[t]["passed"]) for t in TASKS)
        n = sum(int(c[t]["n"]) for t in TASKS)
        check(n == 30, f"{model}/{cond}: n={n}")
        toks[model] = [float(c[t]["context_tokens_median"]) for t in TASKS]
    # Context size is reported from the primary (Claude) leg; flag any cross-model difference.
    tk = toks[MODELS[0]]
    if toks[MODELS[0]] != toks[MODELS[1]]:
        diffs = [t for t, x, y in zip(TASKS, toks[MODELS[0]], toks[MODELS[1]]) if x != y]
        notes.append(f"{cond}: context tokens differ between models on {', '.join(diffs)} "
                     f"(Claude {[int(toks[MODELS[0]][TASKS.index(t)]) for t in diffs]}, "
                     f"Qwen {[int(toks[MODELS[1]][TASKS.index(t)]) for t in diffs]}); table shows Claude")
    rng = "0" if max(tk) == 0 else f"{int(min(tk)):,}–{int(max(tk)):,}"
    med = f"{statistics.median(tk):,.0f}"
    cl, qw = passed[MODELS[0]], passed[MODELS[1]]
    marks = {}
    for model in MODELS:
        extra = replay.get((model, cond), 0)
        # Mark only matched-view cells (the WP12 caveat); report every mover in the notes.
        marks[model] = "ᵃ" if extra and src is wp12 else ""
        if extra:
            notes.append(f"per-edit: {model} {cond}: {passed[model]}/30 published, "
                         f"{passed[model] + extra}/30 under per-edit application"
                         + ("" if src is wp12 else " (7,000-token view; mention in text, not marked)"))
    bold = "**" if cond == "kg_augmented" else ""
    t3.append(f"| {label} | {bold}{rng}{bold} | {bold}{med}{bold} | "
              f"{bold}{cl}/30{bold}{marks[MODELS[0]]} | {bold}{qw}/30{bold}{marks[MODELS[1]]} |")

# The matched budget must be the KG's own per-task context (Claude leg).
kg = cell(wp5, MODELS[0], "kg_augmented")
for cond in ("bm25_matched", "text_emb_3_large_matched"):
    for model in MODELS:
        c = cell(wp12, model, cond)
        for t in TASKS:
            check(int(c[t]["token_budget"]) == int(float(kg[t]["context_tokens_median"])),
                  f"{model}/{cond}/{t}: budget {c[t]['token_budget']} != KG {kg[t]['context_tokens_median']}")

footnote = [n for n in notes if "per-edit" in n]
gen_notes = [f"- {n}" for n in notes if "per-edit" not in n] or ["- none"]
text = "\n".join(
    ["<!-- GENERATED by camera_ready_tables.py from committed artifacts. Do not edit by hand; re-run the script. -->",
     "", "**Table 2.** *[caption drafted in the paper]*", "", *t2, "",
     "**Table 3.** *[caption drafted in the paper]*", "", *t3, "",
     "Anomaly A (per-edit application), for the ᵃ footnote:", *[f"- {n}" for n in footnote], "",
     "Generator notes:", *gen_notes, ""])

if failures:
    print("CONSISTENCY CHECKS FAILED:", *failures, sep="\n  ", file=sys.stderr)
    sys.exit(1)
print(text) if out is None else out.write_text(text)
print(f"OK: all checks passed{'; wrote ' + str(out) if out else ''}", file=sys.stderr)
