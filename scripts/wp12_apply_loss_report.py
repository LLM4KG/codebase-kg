"""WP12 step 8: how much the all-or-nothing applier discarded, and what retention missed.

Three measurements over the 420 candidates of the WP5 + WP12 corpus, all from
artifacts already on disk. No Docker, no API, no network, no writes outside
docs/phase_2/ijckg-2026/ and .cache/.

  M1  all-or-nothing loss     among never-applied candidates, how many had at
                              least one edit that would have applied, and how
                              many of those edits touched a file the model was
                              actually shown
  M2  solution-layer divergence  among passing candidates, how many edited none
                              of the reference patch's files_modified
  M3  corrected retention     beside WP12's published retention fraction, a
                              boolean: does the retrieved set contain some
                              witnessed passing solution?

Why this exists. `docker/apply_edits.js` is all-or-nothing by design — a
half-applied script produces build errors describing a state the model never
asked for. For measurement, though, it collapses "three of four edits were
correct" into `never_applied`, so WP12's matched totals (18, 15, 15, 18) are
**upper bounds on the damage a thin context did, not measurements of it**. M1
says how wide that bound is in candidates. Only step 9
(`scripts/wp12_per_edit_replay.py`) can turn it into a pass count.

The applier, the harness and every condition TOML are untouched by this work.
The Python mirror in `src/evaluation/edit_replay.py` is licensed by the
differential gate below, which runs on every invocation.

Writes docs/phase_2/ijckg-2026/wp12_apply_loss.{md,csv}
   and .cache/wp12_apply_loss/replay_plan.json (the hand-off to step 9).
Run: uv run python scripts/wp12_apply_loss_report.py
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.evaluation.edit_replay import (  # noqa: E402
    Simulation,
    container_source_reader,
    context_files,
    load_script,
    simulate,
)
from src.evaluation.outcomes import grade  # noqa: E402
from src.generation.orchestrator import _load_task_yaml, resolve_repo_root  # noqa: E402
from src.harness.docker_build import verify_pinned_commit  # noqa: E402
from src.harness.tasks import load_pilot_task  # noqa: E402

RESULTS = Path("harness_results")
ARTIFACTS = Path("candidate_artifacts")
TESTS_DIR = Path("tasks/pilot/tests")
RETENTION = Path("docs/phase_2/ijckg-2026/wp12_matched_retrieval.csv")
OUT = Path("docs/phase_2/ijckg-2026/wp12_apply_loss")
PLAN_OUT = Path(".cache/wp12_apply_loss/replay_plan.json")

LEGS = {"claude_primary": "Claude Sonnet 4.6", "qwen_robustness": "Qwen3-Coder"}
TASKS = ["P1", "P2", "P3", "P4", "P5", "P6"]
# The eight runs that hold the WP5 + WP12 corpus, exactly as wp5_outcome_report.py
# and wp12_matched_report.py enumerate them. Listed, never globbed: the results
# directory also holds dry runs, calibration and the superseded July legs.
SUFFIXES = [
    "2026-09-18_wp5_p1p3",
    "2026-09-19_wp5_p1p3_baselines",
    "2026-09-19_wp5_p4p6",
    "2026-09-21_wp12_matched",
]
EXPECTED_CANDIDATES = 420

# Numbers this report must reproduce. A regression in the mirror, the corpus or
# the reader shows up here rather than as a quietly different table.
EXPECTED = {
    "candidates": 420,
    "never_applied": 112,
    "partial": 52,
    "substantive": 42,
    "disjoint_passes": 6,
    "flipped_cells": (
        "P2/dense@7000", "P2/dense@matched",
        "P4/bm25@matched", "P4/dense@matched", "P6/bm25@matched",
    ),
}


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------- #
# Load                                                                        #
# --------------------------------------------------------------------------- #
class Candidate:
    """One corpus candidate, with its artifacts and its simulated verdicts."""

    def __init__(self, leg: str, run: str, row: dict, sim: Simulation,
                 shown: frozenset[str], script) -> None:
        self.leg = leg
        self.run = run
        self.row = row
        self.sim = sim
        self.shown = shown
        self.script = script

    @property
    def id(self) -> str:
        return self.row["candidate_id"]

    @property
    def task(self) -> str:
        return self.row["task_id"]

    @property
    def condition(self) -> str:
        return self.row["condition"]

    @property
    def outcome(self) -> str:
        return grade(self.row)

    @property
    def edited_paths(self) -> list[str]:
        seen: list[str] = []
        for e in self.script.edits:
            if e.path not in seen:
                seen.append(e.path)
        return seen


def load_corpus() -> tuple[list[Candidate], dict[str, str], dict[str, dict]]:
    """Every candidate in the eight runs, with the pin gate run first."""
    readers, task_meta = {}, {}
    for task_id in TASKS:
        task = load_pilot_task(task_id)
        repo_root = resolve_repo_root(task.project_id)
        # Pin gate: every `git show` below assumes the checkout is where the
        # task YAML says it is. A moved checkout would silently answer with a
        # different tree and every verdict after it would be fiction.
        verify_pinned_commit(repo_root, task.git_commit)
        mounts = {tf: TESTS_DIR / Path(tf).name for tf in task.test_files}
        readers[task_id] = container_source_reader(repo_root, task.git_commit, mounts)
        task_meta[task_id] = {
            "project": task.project_id,
            "repo_root": str(repo_root),
            "git_commit": task.git_commit,
            "files_modified": list(_load_task_yaml(task_id).get("files_modified") or []),
            "files_created": list(_load_task_yaml(task_id).get("files_created") or []),
        }

    candidates: list[Candidate] = []
    corpus_hashes: dict[str, str] = {}
    round_trip_failures: list[str] = []
    for leg in LEGS:
        for suffix in SUFFIXES:
            run = f"{leg}_{suffix}"
            index = RESULTS / run / "results.jsonl"
            if not index.exists():
                sys.exit(f"missing {index}")
            corpus_hashes[run] = sha256_of(index)
            for line in index.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                art = ARTIFACTS / run / row["candidate_id"]
                patch = art / "diff.patch"
                if not patch.exists():
                    sys.exit(f"missing artifact {patch}")
                raw = patch.read_text(encoding="utf-8")
                script = load_script(patch)
                # Round-trip gate: the reduction step 9 sends to Docker is built
                # with EditScript.to_json(). If that serialisation does not
                # reproduce the published patch byte-for-byte, a "subset" replay
                # would differ from the original in ways nobody chose.
                if script.to_json() != raw:
                    round_trip_failures.append(f"{run}/{row['candidate_id']}")
                shown = context_files((art / "prompt.txt").read_text(encoding="utf-8"))
                sim = simulate(script, readers[row["task_id"]])
                candidates.append(Candidate(leg, run, row, sim, shown, script))
    if round_trip_failures:
        sys.exit("round-trip gate failed for:\n  " + "\n  ".join(round_trip_failures))
    if len(candidates) != EXPECTED_CANDIDATES:
        sys.exit(f"expected {EXPECTED_CANDIDATES} candidates, found {len(candidates)}")
    return candidates, corpus_hashes, task_meta


# --------------------------------------------------------------------------- #
# Gates                                                                       #
# --------------------------------------------------------------------------- #
def differential_gate(candidates: list[Candidate]) -> None:
    """The gate that licenses a Python mirror of a Node applier.

    For every candidate, the mirror's predicted first failure must equal the
    `apply_reason` the harness recorded, and "no failure" must equal "the stage
    is not diff_apply_fail". Nothing downstream is meaningful without this.
    """
    bad = []
    for c in candidates:
        recorded = c.row.get("apply_reason")
        failed = c.row["stage"] == "diff_apply_fail"
        if c.sim.first_failure != recorded or (c.sim.first_failure is not None) != failed:
            bad.append(
                f"{c.run}/{c.id}: mirror says {c.sim.first_failure!r}, "
                f"harness recorded {recorded!r} at stage {c.row['stage']}"
            )
    if bad:
        sys.exit(
            "differential gate FAILED — src/evaluation/edit_replay.py has drifted from "
            "docker/apply_edits.js and nothing in this report can be trusted:\n  "
            + "\n  ".join(bad)
        )


def retrieved_set_gate(candidates: list[Candidate]) -> None:
    """What a model was shown must be a property of the cell, not of the candidate.

    Retrieval is deterministic given (task, condition), so all five candidates of
    a cell must have been shown the same files; and where `metadata.json` records
    `included_files` (the bm25 and dense arms), the prompt's headers must agree
    with it. A disagreement means the prompt parse and the retriever's own record
    describe different runs.
    """
    by_cell: dict[tuple, set[frozenset[str]]] = defaultdict(set)
    bad = []
    for c in candidates:
        by_cell[(c.leg, c.condition, c.task)].add(c.shown)
        meta = json.loads((ARTIFACTS / c.run / c.id / "metadata.json").read_text(encoding="utf-8"))
        included = (meta.get("retrieval_metadata") or {}).get("included_files")
        if included is not None and set(included) != set(c.shown):
            bad.append(f"{c.run}/{c.id}: prompt headers disagree with included_files")
    for cell, variants in by_cell.items():
        if len(variants) != 1:
            bad.append(f"{cell}: {len(variants)} distinct retrieved sets across its candidates")
    if bad:
        sys.exit("retrieved-set gate failed:\n  " + "\n  ".join(bad))


# --------------------------------------------------------------------------- #
# M3 — witnessed solutions                                                    #
# --------------------------------------------------------------------------- #
def witnessed_solutions(candidates: list[Candidate], task_meta: dict) -> dict[str, dict]:
    """task -> {edited-file set of a passing candidate: the candidate that witnessed it}.

    Paths absent at the pinned commit are removed: a file the task *creates* is
    unretrievable by construction, and blaming a retriever for not returning it
    is the same error `wp12_matched_retrieval_diag.py` already avoids.
    """
    out: dict[str, dict[frozenset[str], dict]] = defaultdict(dict)
    for c in candidates:
        if c.outcome != "passed":
            continue
        created = [p for p in c.edited_paths
                   if p in task_meta[c.task]["files_created"]
                   or not _exists_at_pin(c.task, p, task_meta)]
        pre_existing = frozenset(p for p in c.edited_paths if p not in created)
        out[c.task].setdefault(
            pre_existing,
            {"witness": c.id, "run": c.run, "created": sorted(created)},
        )
    return {t: dict(v) for t, v in out.items()}


_PIN_CACHE: dict[tuple[str, str], bool] = {}


def _exists_at_pin(task_id: str, path: str, task_meta: dict) -> bool:
    key = (task_id, path)
    if key not in _PIN_CACHE:
        from src.evaluation.edit_replay import source_at_commit

        meta = task_meta[task_id]
        _PIN_CACHE[key] = source_at_commit(meta["repo_root"], meta["git_commit"], path) is not None
    return _PIN_CACHE[key]


def retention_rows(solutions: dict[str, dict]) -> list[dict]:
    """WP12's published retention, with a witnessed-sufficiency column beside it."""
    if not RETENTION.exists():
        sys.exit(f"missing {RETENTION} — run scripts/wp12_matched_retrieval_diag.py first")
    rows = []
    with RETENTION.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            retrieved = set(r["included_files"].split(";")) if r["included_files"] else set()
            fits = [s for s in solutions[r["task"]] if s <= retrieved]
            published_sufficient = int(r["target_files_retained"]) == int(r["target_files_modified"])
            sufficient = bool(fits)
            witness = sorted(min(fits, key=lambda s: (len(s), sorted(s)))) if fits else []
            rows.append({
                "task": r["task"],
                "retriever": r["retriever"],
                "budget_label": r["budget_label"],
                "target_files_modified": int(r["target_files_modified"]),
                "target_files_retained": int(r["target_files_retained"]),
                "published_sufficient": published_sufficient,
                "witnessed_solutions": len(solutions[r["task"]]),
                "sufficient": sufficient,
                "flipped": sufficient != published_sufficient,
                "witness": ";".join(witness),
            })
    return rows


# --------------------------------------------------------------------------- #
# Report                                                                      #
# --------------------------------------------------------------------------- #
def short(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def substantive(c: "Candidate") -> bool:
    """True when a surviving edit changes a file that already existed.

    A `write` creates a file and can only fail on a path that escapes the repo,
    so it survives the applier almost by definition. A candidate whose only
    surviving edit is a file creation has none of its *fix* preserved — P3's
    `floor` candidates all create `useCopyToClipboard.ts` and then fail to wire
    it in. Counting those as apply-loss would overstate the artifact.
    """
    return any(c.script.edits[i].op in ("replace", "delete") for i in c.sim.accepted)


def main() -> None:
    candidates, corpus_hashes, task_meta = load_corpus()
    differential_gate(candidates)
    retrieved_set_gate(candidates)

    never = [c for c in candidates if c.outcome == "never_applied"]
    partial = [c for c in never if c.sim.partial]
    passes = [c for c in candidates if c.outcome == "passed"]
    disjoint = [c for c in passes
                if not set(c.edited_paths) & set(task_meta[c.task]["files_modified"])]
    solutions = witnessed_solutions(candidates, task_meta)
    m3 = retention_rows(solutions)
    flipped = [r for r in m3 if r["flipped"]]

    actual = {
        "candidates": len(candidates),
        "never_applied": len(never),
        "partial": len(partial),
        "substantive": sum(1 for c in partial if substantive(c)),
        "disjoint_passes": len(disjoint),
        "flipped_cells": tuple(
            f"{r['task']}/{r['retriever']}@{r['budget_label']}" for r in flipped
        ),
    }
    if actual != EXPECTED:
        sys.exit(f"corpus regression: expected {EXPECTED}, measured {actual}")

    # ---------------- CSV ---------------- #
    fields = [
        "metric", "leg", "model", "run", "condition", "task", "candidate_id", "outcome",
        "edit_index", "edit_path", "edit_op", "edit_applies", "edit_reason",
        "edit_match_count", "edit_path_shown", "edit_path_in_reference",
        "edited_paths", "reference_files_modified",
        "retriever", "budget_label", "target_files_modified", "target_files_retained",
        "published_sufficient", "witnessed_solutions", "sufficient", "flipped", "witness",
    ]
    csv_rows: list[dict] = []
    for c in never:
        ref = set(task_meta[c.task]["files_modified"])
        for v in c.sim.verdicts:
            csv_rows.append({
                "metric": "m1_edit", "leg": c.leg, "model": LEGS[c.leg], "run": c.run,
                "condition": c.condition, "task": c.task, "candidate_id": c.id,
                "outcome": c.outcome, "edit_index": v.index, "edit_path": v.path,
                "edit_op": v.op, "edit_applies": v.applied, "edit_reason": v.reason or "",
                "edit_match_count": "" if v.match_count is None else v.match_count,
                "edit_path_shown": v.path in c.shown,
                "edit_path_in_reference": v.path in ref,
            })
    for c in passes:
        ref = task_meta[c.task]["files_modified"]
        csv_rows.append({
            "metric": "m2_pass", "leg": c.leg, "model": LEGS[c.leg], "run": c.run,
            "condition": c.condition, "task": c.task, "candidate_id": c.id,
            "outcome": c.outcome,
            "edited_paths": ";".join(c.edited_paths),
            "reference_files_modified": ";".join(ref),
        })
    for r in m3:
        csv_rows.append({"metric": "m3_retention", **r})

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.with_suffix(".csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in csv_rows:
            w.writerow({k: r.get(k, "") for k in fields})

    # ---------------- replay plan ---------------- #
    PLAN_OUT.parent.mkdir(parents=True, exist_ok=True)
    plan = {
        "generated_by": "scripts/wp12_apply_loss_report.py",
        "corpus_sha256": corpus_hashes,
        "tasks": {t: {k: task_meta[t][k] for k in ("project", "git_commit")} for t in TASKS},
        "candidates": [
            {
                "leg": c.leg, "run": c.run, "candidate_id": c.id, "task": c.task,
                "condition": c.condition, "model": c.row["model"],
                "project": task_meta[c.task]["project"],
                "edit_count": len(c.script.edits),
                "accepted": list(c.sim.accepted),
                "accepted_paths": sorted({c.script.edits[i].path for i in c.sim.accepted}),
                "recorded_reason": c.row.get("apply_reason"),
            }
            for c in partial
        ],
    }
    PLAN_OUT.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")

    # ---------------- markdown ---------------- #
    md: list[str] = []
    a = md.append
    a("# WP12 — Apply loss and solution-layer divergence")
    a("")
    a("> Generated by `scripts/wp12_apply_loss_report.py` from `harness_results/`,")
    a("> `candidate_artifacts/` and the pinned project checkouts. Do not edit by hand.")
    a("> No Docker, no API, no network. The applier, the harness and every condition")
    a("> TOML are untouched by this work.")
    a("")
    a("## What this measures, and what it cannot")
    a("")
    a("`docker/apply_edits.js` is **all-or-nothing**: edits stage in memory and one failed")
    a("SEARCH aborts the whole script. That is right for the harness — a half-applied script")
    a("produces build errors describing a state the model never asked for — but for")
    a("*measurement* it collapses \"three of four edits were correct\" into `never_applied`.")
    a("")
    a("So WP12's matched totals are **upper bounds on the damage a thin context did, not")
    a("measurements of it**. M1 below says how wide that bound is *in candidates*. Turning it")
    a("into a pass count needs `scripts/wp12_per_edit_replay.py` (step 9); nothing on this")
    a("page moves a pass count.")
    a("")
    a(f"Corpus: **{len(candidates)} candidates** across {len(corpus_hashes)} runs "
      f"({', '.join(SUFFIXES)}, both legs), all `output_format = search_replace`.")
    a("")
    a("### Gate: the Python mirror against the recorded results")
    a("")
    a("`src/evaluation/edit_replay.py` transliterates the applier, differing in exactly one")
    a("respect: it records a verdict and continues where the JS aborts. It is licensed by a")
    a("differential gate that runs on every invocation of this script —")
    a(f"for all **{len(candidates)}** candidates the mirror's predicted first failure equals the")
    a("`apply_reason` the harness recorded, and \"no failure\" equals \"stage is not")
    a("`diff_apply_fail`\". **0 mismatches.** Step 9 cross-checks a further")
    a(f"{len(partial)} of them against the real Node applier inside Docker.")
    a("")

    # M1
    a("## M1 — what the all-or-nothing applier discarded")
    a("")
    a(f"Of **{len(never)}** never-applied candidates, **{len(partial)}** had at least one edit")
    a(f"the applier would have accepted, and **{actual['substantive']}** had at least one that")
    a("changes a file that already existed. Cells with no never-applied candidate are omitted.")
    a("")
    a("Two narrowing columns, because not every surviving edit is a surviving *fix*:")
    a("")
    a("- **edits a file that existed** — a `write` creates a file and can only fail on a path")
    a("  that escapes the repo, so it survives almost by definition. P3's `floor` candidates")
    a("  all create `useCopyToClipboard.ts` and then fail to wire it in; none of their fix")
    a("  survives. Only `replace` and `delete` are counted here.")
    a("- **on a shown file** — the prompt actually carried that file's source, so the model")
    a("  was not guessing at it.")
    a("")
    a("| Model | Condition | Task | never applied | ≥1 edit applies | …edits a file that existed | …on a shown file | edits kept / edits total |")
    a("|---|---|---|---|---|---|---|---|")
    cells = sorted({(c.leg, c.condition, c.task) for c in never},
                   key=lambda k: (list(LEGS).index(k[0]), k[2], k[1]))
    for leg, cond, task in cells:
        group = [c for c in never if (c.leg, c.condition, c.task) == (leg, cond, task)]
        part = [c for c in group if c.sim.partial]
        subst = [c for c in part if substantive(c)]
        shown = [c for c in subst
                 if any(c.script.edits[i].path in c.shown for i in c.sim.accepted
                        if c.script.edits[i].op in ("replace", "delete"))]
        kept = sum(len(c.sim.accepted) for c in group)
        total = sum(len(c.script.edits) for c in group)
        mark = "**" if subst else ""
        a(f"| {LEGS[leg]} | `{cond}` | {task} | {len(group)} | {len(part)} | "
          f"{mark}{len(subst)}{mark} | {len(shown)} | {kept} / {total} |")
    a("")
    reasons = Counter(c.sim.first_failure for c in never)
    a("Recorded causes across the " + str(len(never)) + " never-applied candidates: "
      + ", ".join(f"`{k}` {v}" for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])) + ".")
    a("")

    # Anomaly A focus
    focus = [c for c in candidates
             if c.task == "P2" and c.condition == "text_emb_3_large_matched"]
    a("### Anomaly A — P2 at the matched dense budget")
    a("")
    a("The cell that opened this work: an identical 1,497-token context, Claude 0/5 and Qwen")
    a("5/5. Per candidate, edits that would have applied, and which of them Qwen's passing")
    a("solution also needed.")
    a("")
    a("| Model | Candidate | Outcome | Edits | Would apply | Paths that would apply |")
    a("|---|---|---|---|---|---|")
    for c in sorted(focus, key=lambda c: (list(LEGS).index(c.leg), c.id)):
        paths = sorted({short(c.script.edits[i].path) for i in c.sim.accepted})
        a(f"| {LEGS[c.leg]} | `{c.id.rsplit('__', 1)[-1]}` | {c.outcome} | "
          f"{len(c.script.edits)} | {len(c.sim.accepted)} | {', '.join(paths) or '—'} |")
    a("")

    # M2
    a("## M2 — passing candidates that edited none of the reference's files")
    a("")
    a(f"**{len(disjoint)}** of **{len(passes)}** passing candidates edited no file in their")
    a("task's `files_modified`. These are not anomalies to explain away: the pilot tasks are")
    a("adversarial by construction — tests were written before the reference patch and assert")
    a("on behaviour — so more than one solution layer can satisfy them.")
    a("")
    if disjoint:
        a("| Model | Condition | Task | Candidate | Edited | Reference `files_modified` |")
        a("|---|---|---|---|---|---|")
        for c in sorted(disjoint, key=lambda c: (c.task, c.condition, list(LEGS).index(c.leg), c.id)):
            a(f"| {LEGS[c.leg]} | `{c.condition}` | {c.task} | `{c.id.rsplit('__', 1)[-1]}` | "
              f"{', '.join(short(p) for p in c.edited_paths)} | "
              f"{', '.join(short(p) for p in task_meta[c.task]['files_modified'])} |")
        a("")

    # M3
    a("## M3 — corrected retention: is the retrieved set sufficient?")
    a("")
    a("WP12's retention asks *is every file the reference patch edited still in the context?*")
    a("Where a task admits more than one solution layer that question mis-measures adequacy.")
    a("The column beside it asks instead: **does the retrieved set contain some witnessed")
    a("passing solution?** A witnessed solution is the edited-file set of any passing")
    a("candidate anywhere in the corpus, minus paths absent at the pinned commit — a file the")
    a("task *creates* is unretrievable by construction.")
    a("")
    a("**This is survivorship-biased by construction and is a lower bound on adequacy.** A")
    a("solution counts as witnessed only because some arm happened to retrieve enough to find")
    a("it; solutions no arm found are invisible here. `sufficient = False` therefore means")
    a("\"no *known* solution fits\", never \"no solution exists\".")
    a("")
    a("It is also **not** a predictor of passing. P4's matched cells are sufficient under this")
    a("test and still passed 0/5 on the Claude leg — the files were there and the models did")
    a("not use them. Sufficiency bounds what retrieval can be blamed for; it does not claim")
    a("the rest.")
    a("")
    a("Witnessed solutions per task: "
      + ", ".join(f"{t} {len(solutions[t])}" for t in TASKS) + ".")
    a("")
    a("| Task | Retriever | Budget | Published retention | Published verdict | Sufficient | Witnessing solution |")
    a("|---|---|---|---|---|---|---|")
    for r in m3:
        mark = " **⟵ flips**" if r["flipped"] else ""
        wit = ", ".join(short(p) for p in r["witness"].split(";")) if r["witness"] else "—"
        a(f"| {r['task']} | {r['retriever']} | {r['budget_label']} | "
          f"{r['target_files_retained']}/{r['target_files_modified']} | "
          f"{'sufficient' if r['published_sufficient'] else 'insufficient'} | "
          f"{'**yes**' if r['sufficient'] else 'no'}{mark} | {wit} |")
    a("")
    a(f"**{len(flipped)} of {len(m3)} cells flip**: "
      + ", ".join(f"`{r['task']}/{r['retriever']}@{r['budget_label']}`" for r in flipped)
      + ". All flip the same way — published retention said the context was inadequate and a")
    a("witnessed solution says it was not. None flips the other way, which is what makes this")
    a("a correction to the metric rather than a different metric.")
    a("")
    a("> The step 8–9 plan predicted two flips, both at the matched budget. It was written")
    a("> before witnessed solutions were computed over the whole corpus and was wrong: there")
    a(f"> are {len(flipped)}, and one of them (P2/dense@7,000) is a **published** cell, not a matched one.")
    a("> The prediction is recorded here rather than quietly dropped.")
    a("")

    a("## What this does not show")
    a("")
    a("- **No pass count moves.** M1 counts candidates with a surviving edit, not passes. A")
    a("  candidate whose kept edits are the whole fix and one whose kept edits are cosmetic")
    a("  are one row each here; only step 9 tells them apart.")
    a("- **M1 is not a proposal to change the applier.** All-or-nothing stays exactly as")
    a("  published, or WP5 comparability breaks.")
    a("- **M3 cannot see unwitnessed solutions** (above), and is not evidence that a")
    a("  sufficient context produces a pass.")
    a("")
    a("## Sources")
    a("")
    a("| Run | `results.jsonl` sha256 |")
    a("|---|---|")
    for run, digest in sorted(corpus_hashes.items()):
        a(f"| `{run}` | `{digest[:16]}…` |")
    a("")
    a(f"Step 9's hand-off, carrying those hashes and the {len(partial)} candidates to replay: "
      f"`{PLAN_OUT}` (gitignored).")
    a("")

    OUT.with_suffix(".md").write_text("\n".join(md), encoding="utf-8")
    print(f"wrote {OUT.with_suffix('.md')}, {OUT.with_suffix('.csv')} and {PLAN_OUT}")
    print(f"  {len(candidates)} candidates, differential gate 0 mismatches")
    print(f"  M1 {len(partial)}/{len(never)} never-applied had >=1 applying edit, "
          f"{actual['substantive']} of them on a pre-existing file")
    print(f"  M2 {len(disjoint)}/{len(passes)} passes edited none of files_modified")
    print(f"  M3 {len(flipped)}/{len(m3)} retention cells flip")


if __name__ == "__main__":
    main()
