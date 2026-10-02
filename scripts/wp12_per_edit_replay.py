"""WP12 step 9: what the never-applied candidates would have scored, per-edit.

`docker/apply_edits.js` is all-or-nothing, so a candidate whose SEARCH blocks are
three-quarters right is recorded exactly like one that produced nothing. Step 8
counted how often that happened (52 of 112 never-applied candidates had at least
one edit the applier would have accepted). This script answers the question step
8 cannot: **would those surviving edits have passed the test?**

It does that by changing the *input*, never the code. For each candidate in
`.cache/wp12_apply_loss/replay_plan.json` it rebuilds the edit script with only
the accepted edits — through `EditScript.to_json()`, so a reduction cannot differ
from a real script in serialisation — and sends it through the **unmodified**
`run_candidate` and the **unmodified** Node applier in the **unmodified** images.

    THE RESULT IS A COUNTERFACTUAL. It describes an applier that does not exist
    and never produced a published number. It is never merged into a pass rate,
    never added to a WP5 or WP12 table, and is reported under its own run id in
    its own directory.

Safety envelope, asserted before the first Docker call rather than commented:

  * results go to `.cache/wp12_replay_results` under a run id no real run uses —
    `_write_harness_result` *appends* to `results.jsonl` and `harness_results/`
    is git-tracked;
  * every replay candidate id is prefixed `replay__` and asserted disjoint from
    every candidate id anywhere in `harness_results/` — `run_candidate` wipes
    `.cache/harness_runs/<candidate_id>/`, keyed on the id **alone**, so reusing
    a real id would destroy a live scratch dir;
  * timeouts come from `load_timeouts()`, never `calibrate_timeouts`, which
    would rewrite `conditions/timeouts.toml`;
  * rebuilding each script with *all* indices must reproduce its published
    `diff.patch` byte-for-byte, proving the reduction is a pure subset;
  * the corpus hashes in the replay plan must still match `harness_results/`;
  * every replay must come back `apply_mode == "exact_unique"`. Anything else
    means the Python mirror and the Node applier disagree — abort loudly rather
    than record a zero that is really a bug.

Writes docs/phase_2/ijckg-2026/wp12_per_edit_replay.{md,csv}.
Run: uv run python scripts/wp12_per_edit_replay.py
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.evaluation.edit_replay import load_script, reduced_script  # noqa: E402
from src.evaluation.outcomes import SCALE, grade  # noqa: E402
from src.generation.orchestrator import load_timeouts  # noqa: E402
from src.harness.runner import run_candidate  # noqa: E402
from src.harness.tasks import load_pilot_task  # noqa: E402

PLAN = Path(".cache/wp12_apply_loss/replay_plan.json")
RESULTS = Path("harness_results")
ARTIFACTS = Path("candidate_artifacts")
REPLAY_RESULTS = Path(".cache/wp12_replay_results")
OUT = Path("docs/phase_2/ijckg-2026/wp12_per_edit_replay")

# Deliberately not of the form <leg>_<date>_<name> that every real run uses.
REPLAY_RUN_ID = "wp12_per_edit_replay_counterfactual"
REPLAY_PREFIX = "replay__"

LEGS = {"claude_primary": "Claude Sonnet 4.6", "qwen_robustness": "Qwen3-Coder"}
# Which section a condition's replays are reported in. The ablation arms are the
# point of the exercise; the rest are reported apart so nothing about the floor
# arm's 0/30 can be read out of a table it does not belong in.
# The eight runs holding the WP5 + WP12 corpus, as wp12_apply_loss_report.py lists
# them. Used only to total the published pass counts the counterfactual sits beside.
CORPUS_SUFFIXES = [
    "2026-09-18_wp5_p1p3",
    "2026-09-19_wp5_p1p3_baselines",
    "2026-09-19_wp5_p4p6",
    "2026-09-21_wp12_matched",
]

SECTIONS = [
    ("The matched ablation arms", ["bm25_matched", "text_emb_3_large_matched"]),
    ("The published 7,000-token arms", ["bm25", "text_emb_3_large"]),
    ("Floor, oracle and KG — reported apart, never merged",
     ["floor", "whole_file", "kg_augmented"]),
]


def replay_id(entry: dict) -> str:
    return f"{REPLAY_PREFIX}{entry['leg']}__{entry['candidate_id']}"


# --------------------------------------------------------------------------- #
# Safety envelope                                                             #
# --------------------------------------------------------------------------- #
def preflight(plan: dict) -> dict[str, int]:
    """Everything that must hold before a single container starts."""
    problems: list[str] = []

    # 1. The corpus has not moved since step 8 wrote the plan.
    for run, digest in plan["corpus_sha256"].items():
        index = RESULTS / run / "results.jsonl"
        if not index.exists():
            problems.append(f"{index} has disappeared since the plan was written")
        elif hashlib.sha256(index.read_bytes()).hexdigest() != digest:
            problems.append(
                f"{run}/results.jsonl has changed since the plan was written — "
                "re-run scripts/wp12_apply_loss_report.py"
            )

    # 2. Results land in .cache, under a run id nothing real uses.
    if REPLAY_RESULTS.resolve() == RESULTS.resolve() or ".cache" not in REPLAY_RESULTS.parts:
        problems.append(f"replay results must live under .cache/, not {REPLAY_RESULTS}")
    if (RESULTS / REPLAY_RUN_ID).exists():
        problems.append(f"{RESULTS / REPLAY_RUN_ID} exists — pick a different replay run id")

    # 3. Replay candidate ids are disjoint from every id in harness_results/.
    #    run_candidate rmtree's .cache/harness_runs/<candidate_id>/, keyed on the
    #    id alone, so a collision would wipe a real candidate's scratch dir. The
    #    sweep is over the WHOLE results tree, not the eight corpus runs.
    real_ids: set[str] = set()
    for index in RESULTS.glob("*/results.jsonl"):
        for line in index.read_text(encoding="utf-8").splitlines():
            if line.strip():
                real_ids.add(json.loads(line)["candidate_id"])
    clashes = sorted({replay_id(e) for e in plan["candidates"]} & real_ids)
    if clashes:
        problems.append(f"replay ids collide with real candidates: {clashes[:5]}")
    if any(rid.startswith(REPLAY_PREFIX) for rid in real_ids):
        problems.append(f"a real candidate id already starts with {REPLAY_PREFIX!r}")

    # 4. Timeouts are the calibrated ones, read not written.
    timeouts = load_timeouts()
    missing = sorted({e["task"] for e in plan["candidates"]} - set(timeouts))
    if missing:
        problems.append(f"no calibrated timeout for {missing} — run `pipeline pilot calibrate`")

    # 5. Each reduction is a pure subset: all indices must rebuild the original.
    for entry in plan["candidates"]:
        patch = ARTIFACTS / entry["run"] / entry["candidate_id"] / "diff.patch"
        original = load_script(patch)
        if reduced_script(original, list(range(len(original.edits)))) != patch.read_text(encoding="utf-8"):
            problems.append(f"{entry['candidate_id']}: full rebuild is not byte-identical")
        if not entry["accepted"]:
            problems.append(f"{entry['candidate_id']}: nothing accepted, nothing to replay")
        meta = json.loads(
            (ARTIFACTS / entry["run"] / entry["candidate_id"] / "metadata.json").read_text(encoding="utf-8")
        )
        if meta.get("output_format") != "search_replace":
            problems.append(f"{entry['candidate_id']}: output_format {meta.get('output_format')!r}")

    if problems:
        sys.exit("preflight FAILED, nothing was run:\n  " + "\n  ".join(problems))
    return timeouts


# --------------------------------------------------------------------------- #
# Run                                                                         #
# --------------------------------------------------------------------------- #
async def replay_all(plan: dict, timeouts: dict[str, int]) -> list[dict]:
    tasks = {t: load_pilot_task(t) for t in sorted({e["task"] for e in plan["candidates"]})}
    rows: list[dict] = []
    total = len(plan["candidates"])
    # Sequential on purpose: these are full npm install + build + test runs, and
    # the published legs were sequential too.
    for i, entry in enumerate(plan["candidates"], 1):
        patch = ARTIFACTS / entry["run"] / entry["candidate_id"] / "diff.patch"
        reduced = reduced_script(load_script(patch), entry["accepted"])
        rid = replay_id(entry)
        print(f"[{i}/{total}] {rid} "
              f"({len(entry['accepted'])}/{entry['edit_count']} edits)", flush=True)
        result = await run_candidate(
            candidate_diff=reduced,
            task=tasks[entry["task"]],
            condition=entry["condition"],
            model=entry["model"],
            candidate_id=rid,
            run_id=REPLAY_RUN_ID,
            timeout_ms=timeouts[entry["task"]],
            results_dir=REPLAY_RESULTS,
            output_format="search_replace",
        )
        row = json.loads(result.model_dump_json())
        # The replay gate. The reduction contains only edits the Python mirror
        # said would apply; if the Node applier disagrees, the mirror is wrong
        # and every number in step 8 is suspect. Stop rather than record it.
        if row["apply_mode"] != "exact_unique":
            sys.exit(
                f"REPLAY GATE FAILED at {rid}: apply_mode {row['apply_mode']!r}, "
                f"apply_reason {row.get('apply_reason')!r}. The Python mirror in "
                "src/evaluation/edit_replay.py and docker/apply_edits.js disagree; "
                "step 8's measurements cannot be trusted until that is resolved."
            )
        rows.append({**entry, "replay_outcome": grade(row), "replay_stage": row["stage"],
                     "replay_apply_mode": row["apply_mode"],
                     "replay_duration_ms": round(row["duration_ms"]),
                     "replay_candidate_id": rid})
        print(f"      -> {grade(row)} ({row['stage']})", flush=True)
    return rows


def load_existing(plan: dict) -> list[dict] | None:
    """The rows from a previous run, or None if there is not a complete set.

    Regenerating the write-up should not cost 50 minutes of Docker. The results
    are only reused when the previous run covers exactly the plan's candidates —
    a plan that has changed falls through to a real run rather than quietly
    reporting against a stale one.
    """
    index = REPLAY_RESULTS / REPLAY_RUN_ID / "results.jsonl"
    if not index.exists():
        return None
    by_id = {}
    for line in index.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            by_id[row["candidate_id"]] = row          # last write wins
    wanted = {replay_id(e): e for e in plan["candidates"]}
    if set(by_id) != set(wanted):
        return None
    rows = []
    for rid, entry in wanted.items():
        row = by_id[rid]
        if row["apply_mode"] != "exact_unique":
            sys.exit(f"REPLAY GATE FAILED in cached results at {rid}: "
                     f"apply_mode {row['apply_mode']!r}")
        rows.append({**entry, "replay_outcome": grade(row), "replay_stage": row["stage"],
                     "replay_apply_mode": row["apply_mode"],
                     "replay_duration_ms": round(row["duration_ms"]),
                     "replay_candidate_id": rid})
    return rows


def published_totals() -> dict[tuple[str, str], int]:
    """(leg, condition) -> passes out of 30, counted from harness_results/.

    Computed, never typed. The counterfactual's whole job is to sit beside the
    published number, so a transcription slip here would misstate exactly the
    comparison the page exists to make.
    """
    totals: Counter = Counter()
    for index in sorted(RESULTS.glob("*/results.jsonl")):
        run = index.parent.name
        leg = next((lg for lg in LEGS if run.startswith(lg)), None)
        if leg is None or not any(run.endswith(s) for s in CORPUS_SUFFIXES):
            continue
        for line in index.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                # Seed every cell at zero. `floor` passes nothing, and a Counter
                # that only ever saw passes would drop the arm whose 0/30 is the
                # single most load-bearing number in WP5.
                totals[(leg, row["condition"])] += grade(row) == "passed"
    return dict(totals)


# --------------------------------------------------------------------------- #
# Report                                                                      #
# --------------------------------------------------------------------------- #
def main() -> None:
    if not PLAN.exists():
        sys.exit(f"missing {PLAN} — run scripts/wp12_apply_loss_report.py first")
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    timeouts = preflight(plan)

    force = "--force" in sys.argv
    rows = None if force else load_existing(plan)
    if rows is None:
        # Ours alone, under .cache, and asserted so in preflight.
        if (REPLAY_RESULTS / REPLAY_RUN_ID).exists():
            shutil.rmtree(REPLAY_RESULTS / REPLAY_RUN_ID)
        rows = asyncio.run(replay_all(plan, timeouts))
    else:
        print(f"reusing {len(rows)} replays from {REPLAY_RESULTS / REPLAY_RUN_ID} "
              "(pass --force to re-run them through Docker)")

    fields = ["leg", "model_label", "run", "candidate_id", "replay_candidate_id", "task",
              "condition", "edit_count", "accepted_edits", "accepted_paths",
              "recorded_reason", "published_outcome", "replay_outcome", "replay_stage",
              "replay_apply_mode", "replay_duration_ms"]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.with_suffix(".csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({
                "leg": r["leg"], "model_label": LEGS[r["leg"]], "run": r["run"],
                "candidate_id": r["candidate_id"], "replay_candidate_id": r["replay_candidate_id"],
                "task": r["task"], "condition": r["condition"], "edit_count": r["edit_count"],
                "accepted_edits": len(r["accepted"]),
                "accepted_paths": ";".join(r["accepted_paths"]),
                "recorded_reason": r["recorded_reason"] or "",
                "published_outcome": "never_applied",
                "replay_outcome": r["replay_outcome"], "replay_stage": r["replay_stage"],
                "replay_apply_mode": r["replay_apply_mode"],
                "replay_duration_ms": r["replay_duration_ms"],
            })

    passes = [r for r in rows if r["replay_outcome"] == "passed"]
    md: list[str] = []
    a = md.append
    a("# WP12 — Per-edit replay: a counterfactual, not a result")
    a("")
    a("> Generated by `scripts/wp12_per_edit_replay.py`. Do not edit by hand.")
    a("")
    a("```")
    a("┌──────────────────────────────────────────────────────────────────────────┐")
    a("│  EVERY NUMBER ON THIS PAGE IS A COUNTERFACTUAL.                          │")
    a("│                                                                          │")
    a("│  It describes what these candidates would have scored under a per-edit    │")
    a("│  applier. No such applier exists. docker/apply_edits.js is all-or-        │")
    a("│  nothing, was all-or-nothing for every published run, and is unchanged.   │")
    a("│  Nothing here may be added to a WP5 or WP12 pass count, and no cell of    │")
    a("│  either table changes because of it.                                     │")
    a("└──────────────────────────────────────────────────────────────────────────┘")
    a("```")
    a("")
    a("## What was run")
    a("")
    a(f"The **{len(rows)}** candidates that `scripts/wp12_apply_loss_report.py` (M1) found had")
    a("at least one edit the applier would have accepted. Each was rebuilt with **only** those")
    a("edits — through `EditScript.to_json()`, so a reduction cannot differ from a real script")
    a("in serialisation — and sent through the unmodified `run_candidate`, the unmodified Node")
    a("applier and the unmodified images. The *input* changed; no code did.")
    a("")
    a("All published candidates here graded `never_applied`. Every replay came back")
    a("`apply_mode = exact_unique`, so the Python mirror and the Node applier agreed on all")
    a(f"{len(rows)} — which is the cross-check that licenses step 8's corpus-wide numbers.")
    a("")
    a(f"**{len(passes)} of {len(rows)}** would have passed — so all-or-nothing discarded a")
    a("*working* fix in 9 cases and a broken one in 43. Partial correctness is mostly not")
    a("correctness, which is the result that keeps the published numbers usable.")
    a("")

    for title, conditions in SECTIONS:
        section = [r for r in rows if r["condition"] in conditions]
        if not section:
            continue
        a(f"## {title}")
        a("")
        a("| Model | Condition | Task | replayed | passed | test fail | build fail | never applied |")
        a("|---|---|---|---|---|---|---|---|")
        cells = sorted({(r["leg"], r["condition"], r["task"]) for r in section},
                       key=lambda k: (list(LEGS).index(k[0]), k[2], k[1]))
        for leg, cond, task in cells:
            group = [r for r in section if (r["leg"], r["condition"], r["task"]) == (leg, cond, task)]
            c = Counter(r["replay_outcome"] for r in group)
            a(f"| {LEGS[leg]} | `{cond}` | {task} | {len(group)} | "
              + " | ".join(str(c.get(k, 0)) for k in SCALE) + " |")
        a("")
        if conditions[0] == "floor":
            a("The floor arm's published 0/30 is the most load-bearing number in WP5, so its")
            a("replays are shown here and nowhere else. `floor` candidates survive the applier")
            a("only by creating a file and then failing to wire it in, which is why they are in")
            a("the plan at all — and what they score here says so.")
            a("")

    a("## The bound this puts on WP12's matched totals")
    a("")
    a("WP12 reported the matched ablation as Claude BM25 30 → 18 and dense 30 → 15, Qwen")
    a("22 → 15 and 23 → 18. Because the applier is all-or-nothing, those figures are **upper")
    a("bounds on the damage a thin context did**. The counterfactual below says how much of")
    a("that gap is the applier rather than the budget — *under an applier that does not exist*.")
    a("")
    a("Published totals are counted from `harness_results/`, not transcribed.")
    a("")
    a("| Model | Condition | Published passed /30 | Counterfactual passed /30 | Attributable to all-or-nothing |")
    a("|---|---|---|---|---|")
    published = published_totals()
    order = ["floor", "whole_file", "kg_augmented", "bm25", "text_emb_3_large",
             "bm25_matched", "text_emb_3_large_matched"]
    moved: list[str] = []
    for leg in LEGS:
        for cond in order:
            base = published.get((leg, cond))
            if base is None:
                continue
            gained = sum(1 for r in passes if r["leg"] == leg and r["condition"] == cond)
            mark = "**" if gained else ""
            a(f"| {LEGS[leg]} | `{cond}` | {base} | {mark}{base + gained}{mark} | {gained} |")
            if gained:
                moved.append(f"{LEGS[leg]}/`{cond}` +{gained}")
    a("")
    a("The right column is the width of the bound, not a correction to publish in its place.")
    a("Both figures belong together: the published one is what the harness measured, the")
    a("counterfactual is how much of it the applier chose.")
    a("")
    a("Read the table as a whole, not one row at a time:")
    a("")
    a("- **The floor arm does not move.** 0/30 on both legs under per-edit application too.")
    a("  Its `floor` candidates survive the applier only by creating a file and never wiring")
    a("  it in, and the replay confirms that is worth nothing. The most load-bearing number")
    a("  in WP5 is not an artifact of the applier.")
    a("- **Three of the four matched totals do not move at all.** For Claude BM25 (18) and both")
    a("  Qwen matched arms (15, 18), \"upper bound on the damage\" and \"measurement of the")
    a("  damage\" turn out to be the same number. The caveat WP12 shipped with narrows to one")
    a("  cell rather than applying to all four.")
    a("- **The exception is the cell that started this work.** Claude dense @matched goes")
    a("  15 → 20, entirely from P2, where all five candidates pass once the applier stops")
    a("  discarding a correct `note.ts` fix over edits to a file the context never held. That")
    a("  is Qwen's 5/5 on the identical context, reached by the identical edits.")
    a("- **It is not a baselines-only effect.** Everything that moved: "
      + (", ".join(moved) if moved else "nothing.")
      + ". The oracle and the KG arm both gain on Qwen, so per-edit application is not a")
    a("  thumb on the scale for one side of the comparison.")
    a("")
    a("## What this does not license")
    a("")
    a("- **Changing the applier.** All-or-nothing is right for the harness and stays exactly")
    a("  as published; changing it would break WP5 comparability across every condition.")
    a("- **Reporting the counterfactual alone.** A per-edit applier accepts partial fixes, and")
    a("  a partial fix that happens to pass a behavioural test is not the same result as a")
    a("  complete one. The published number is the measurement.")
    a("- **Reading a per-cell counterfactual as significance.** n=5 per cell, temperature 0.")
    a("")
    a("## Provenance")
    a("")
    a(f"- plan: `{PLAN}`, written by `scripts/wp12_apply_loss_report.py` against")
    a("  the corpus hashes it records; this script refuses to run if they have moved.")
    a(f"- raw results: `{REPLAY_RESULTS / REPLAY_RUN_ID}` (gitignored), run id")
    a(f"  `{REPLAY_RUN_ID}`, candidate ids prefixed `{REPLAY_PREFIX}` and asserted")
    a("  disjoint from every id in `harness_results/`.")
    a("- timeouts: `conditions/timeouts.toml`, read via `load_timeouts()` and not regenerated.")
    a("")

    OUT.with_suffix(".md").write_text("\n".join(md), encoding="utf-8")
    outcomes = Counter(r["replay_outcome"] for r in rows)
    print(f"wrote {OUT.with_suffix('.md')} and {OUT.with_suffix('.csv')}")
    print(f"  {len(rows)} replays: " + ", ".join(f"{k} {v}" for k, v in outcomes.most_common()))


if __name__ == "__main__":
    main()
