"""Build the WP6 annotation set: seeded stratified sample + pre-filled annotation files.

Plan: docs/phase_2/ijckg-2026/wp6_annotation_plan.md
Guide: docs/phase_2/ijckg-2026/annotation_guide.md

Reads the committed graphs of record (graph_export/<project>/full_dump.cypherl)
and the sample-project checkouts, which must be clean and at each graph's
recorded SHA. Deterministic: re-running writes byte-identical files. Refuses to
overwrite an annotation file whose status is no longer `todo`.

Run: uv run python scripts/wp6_build_annotation_set.py
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.evaluation.annotation import (  # noqa: E402
    Header,
    coverage_types,
    items_by_evidence_file,
    parse_annotation_file,
    render_annotation_file,
    sample_files,
)
from src.evaluation.kg_dump import load_dump  # noqa: E402

SEED = 20260920
REPOS_ROOT = Path("~/Study/Implementation/sample-projects").expanduser()
# Smallest first: annotation that runs out of time leaves whole repos complete.
PROJECTS = {
    "react-shopping-cart": ("small/react-shopping-cart", 6),
    "SnapShot": ("small/SnapShot", 5),
    "todoist": ("small/todoist", 5),
    "takenote": ("medium/takenote", 6),
    "jira_clone": ("medium/jira_clone/client", 6),
}
EMPTY_PER_PROJECT = 1
SECOND_ANNOTATOR_REPOS = ["react-shopping-cart", "SnapShot", "todoist", "takenote"]
OUT = Path("annotations/wp6")
LANG = {".js": "js", ".jsx": "jsx", ".ts": "ts", ".tsx": "tsx"}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def checkout(project: str, sha: str) -> Path:
    rel, _ = PROJECTS[project]
    path = REPOS_ROOT / rel
    head = git(path, "rev-parse", "HEAD").strip()
    if head != sha:
        sys.exit(f"{project}: checkout is at {head[:7]}, graph was extracted at {sha[:7]}")
    if git(path, "status", "--porcelain", "--", ".").strip():
        sys.exit(f"{project}: checkout {path} has local changes")
    return path


def slug(path: str) -> str:
    return path.replace("/", "__")


def write_guarded(path: Path, text: str) -> None:
    if path.exists():
        current = path.read_text(encoding="utf-8")
        if current == text:
            return
        status = parse_annotation_file(current).status
        if status != "todo":
            sys.exit(f"refusing to overwrite {path}: status is {status!r}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    order = list(PROJECTS)
    item_sets, provenance, types_by_file, roots = {}, {}, {}, {}
    for proj in order:
        prov = json.loads(Path(f"graph_export/{proj}/manifest.json").read_text())["provenance"]
        provenance[proj] = prov
        roots[proj] = checkout(proj, prov["repo_commit_sha"])
        item_sets[proj] = items_by_evidence_file(load_dump(f"graph_export/{proj}/full_dump.cypherl"))
        types_by_file[proj] = {f: coverage_types(items) for f, items in item_sets[proj].by_file.items()}

    # Files with no LLM-extracted items (barrels, styles, utilities: 105 of 283)
    # form their own stratum, one file per repo, so whole-file misses are measured
    # without spending a third of the budget where there is nothing to score.
    empty = {
        p: {f for f, items in item_sets[p].by_file.items() if not any(i.scope == "llm" for i in items)}
        for p in order
    }
    picks = sample_files(
        types_by_file, {p: PROJECTS[p][1] for p in order}, SEED, order,
        empty_files=empty, empty_per_project=EMPTY_PER_PROJECT,
    )

    rng = random.Random(SEED + 1)
    second = {
        (proj, rng.choice(sorted(p.path for p in picks if p.project == proj)))
        for proj in SECOND_ANNOTATOR_REPOS
    }

    entries = []
    for n, pick in enumerate(picks, 1):
        prov = provenance[pick.project]
        sha = prov["repo_commit_sha"]
        items = item_sets[pick.project].by_file[pick.path]
        header = Header(
            project=pick.project,
            path=pick.path,
            sha=sha,
            prompt_set=prov["prompt_set_version"],
            graph=f"graph_export/{pick.project}/full_dump.cypherl",
        )
        source = (roots[pick.project] / pick.path).read_text(encoding="utf-8")
        text = render_annotation_file(header, source, items, LANG.get(Path(pick.path).suffix, ""))
        name = f"{n:02d}_{pick.project}__{slug(pick.path)}.md"
        write_guarded(OUT / name, text)
        is_second = (pick.project, pick.path) in second
        if is_second:
            write_guarded(OUT / "second_annotator" / name, text)
        entries.append({
            "n": n,
            "project": pick.project,
            "path": pick.path,
            "file": name,
            "reason": pick.reason,
            "stratum": "no_llm_items" if pick.path in empty[pick.project] else "content",
            "second_annotator": is_second,
            "source_lines": source.count("\n") + 1,
            "items": {
                "llm_nodes": sum(1 for i in items if i.scope == "llm" and i.kind == "N"),
                "llm_edges": sum(1 for i in items if i.scope == "llm" and i.kind == "E"),
                "deterministic": sum(1 for i in items if i.scope == "deterministic"),
            },
            "types": sorted(types_by_file[pick.project][pick.path]),
        })

    present = defaultdict(int)
    for proj in order:
        for types in types_by_file[proj].values():
            for t in types:
                present[t] += 1
    covered = {t for e in entries for t in e["types"]}
    coverage = {
        t: {"files_with_type": present[t], "sampled_files": [e["n"] for e in entries if t in e["types"]]}
        for t in sorted(present)
    }

    sample = {
        "seed": SEED,
        "plan": "docs/phase_2/ijckg-2026/wp6_annotation_plan.md",
        "quotas": {p: PROJECTS[p][1] for p in order},
        "strata": {
            "content": "files with at least one LLM-extracted item (coverage pass + fill)",
            "no_llm_items": f"{EMPTY_PER_PROJECT} per repo from files with no LLM-extracted items",
            "no_llm_item_files_in_graphs": {p: len(empty[p]) for p in order},
        },
        "graphs": {
            p: {
                "dump": f"graph_export/{p}/full_dump.cypherl",
                "repo_commit_sha": provenance[p]["repo_commit_sha"],
                "prompt_set_version": provenance[p]["prompt_set_version"],
                "extraction_model": provenance[p]["extraction_model"],
                "files_in_graph": len(item_sets[p].by_file),
                "package_level_items": len(item_sets[p].package),
                "excluded_items": len(item_sets[p].excluded),
            }
            for p in order
        },
        "not_annotated": {
            "IMPORTS": "in the schema but never created by the pipeline",
            "Project/Library/DEPENDS_ON": "package-level; checked against package.json by WP7",
            "Library_Hook nodes": "global; scored through their USES_LIBRARY_HOOK / PROVIDED_BY edges",
        },
        "coverage": coverage,
        "uncovered_types": sorted(set(present) - covered),
        "files": entries,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "sample.json").write_text(json.dumps(sample, indent=2) + "\n", encoding="utf-8")

    print(f"{len(entries)} files, seed {SEED} -> {OUT}/")
    for e in entries:
        i = e["items"]
        flag = " [2nd]" if e["second_annotator"] else ""
        print(f"  {e['n']:2d} {e['project']:<20} {e['path']:<60} "
              f"{e['source_lines']:>4} lines  {i['llm_nodes']:>3}N {i['llm_edges']:>3}E "
              f"{i['deterministic']:>2}D  {e['reason']}{flag}")
    print("coverage (type: files in graphs -> sampled files):")
    for t, c in coverage.items():
        print(f"  {t:<24} {c['files_with_type']:>4} -> {c['sampled_files']}")
    print("uncovered:", sample["uncovered_types"] or "none")
    total = defaultdict(int)
    for e in entries:
        for k, v in e["items"].items():
            total[k] += v
    print("items to review:", dict(total), "source lines:", sum(e["source_lines"] for e in entries))


if __name__ == "__main__":
    main()
