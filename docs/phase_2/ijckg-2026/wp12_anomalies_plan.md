# WP12 steps 8–9 — Applier loss and solution-layer divergence: implementation plan

> Written 21 Sep 2026, after WP12 steps 0–7 landed. Resolves the two open items in
> [`wp12_matched_context.md`](wp12_matched_context.md) §"Two anomalies to resolve before
> publishing". Kept separate from [`wp12_matched_context_plan.md`](wp12_matched_context_plan.md),
> which is a completed record: these steps were *discovered by executing* that plan rather than
> planned beside it, and one of them corrects a metric that plan's own results depend on.
> Referenced from that plan and from §2 of
> [`revision_implementation_plan_18-22Sep.md`](revision_implementation_plan_18-22Sep.md).
> Supersedes nothing: every WP5 and WP12 artifact stays exactly as published.

## Context

WP12 reported the matched ablation as Claude BM25 30 → 18 and dense 30 → 15, Qwen 22 → 15 and
23 → 18, against an unchanged KG arm of 25 and 16. Two cells did not behave, and both were left as
open questions in the note. They are now diagnosed, and the diagnosis changes what WP12 may claim.

### Anomaly A — the applier, not the model

**P2 @ `text_emb_3_large_matched`: Claude 0/5, Qwen 5/5 on an identical 1,497-token context.**

`docker/apply_edits.js` is **all-or-nothing**: edits stage in memory and a single failed SEARCH
aborts the whole script. That is right for safety — a half-edited repo is worse than none — but for
*measurement* it collapses "mostly correct" into `never_applied`.

The retrieved context held `note.ts` but not `containers/NoteList.tsx` or `resources/TestID.ts`
(2 of 3 reference targets). Claude attempted the full reference-shaped fix, four edits; Qwen
attempted `note.ts` only, two edits, and passed. Replaying Claude's SEARCH blocks against the tree:

| candidate | edits that would apply | killed by |
|---|---|---|
| n1 | **3 of 4** | one bad SEARCH in `NoteList.tsx` |
| n2 | 2 of 4 | two in `NoteList.tsx` |
| n3 | **3 of 4** | one in `NoteList.tsx` |
| n4 | 2 of 4 | two in `NoteList.tsx` |
| n5 | 2 of 4 | two in `NoteList.tsx` |

In **all five**, both `note.ts` edits would have applied — exactly the two edits Qwen passed with.
n1 and n3 also reconstructed a `NoteList.tsx` hunk correctly without ever seeing the file. So
Claude's 0/5 is not a failure to solve P2; it is the applier discarding a correct reducer fix
because the model *also* attempted the part its context did not cover. Under per-edit application
this cell plausibly becomes 5/5, moving dense @matched from 15/30 to 20/30.

**Consequence: "30 → 18" and "30 → 15" are upper bounds on the damage, not measurements.** The
paper cannot state them as measurements without knowing the artifact's width. This is the one thing
in WP12 that is currently overstated.

### Anomaly B — the metric, not the harness

**P6 @ `bm25_matched`: the reference target retained 0/1, yet 3/5 passed on each leg.**

All ten candidates fixed `src/client/slices/category.ts` — a file BM25 **did** retrieve — at the
reducer layer, which `P6.yaml` explicitly blesses as valid. The test drives the real component
through a real store and asserts on store state, so a guard in the slice satisfies it. One
candidate (claude n1) also emitted an edit for `src/client/components/AppSidebar/CategoryList.tsx`,
**a path that does not exist** at the pinned commit, and was killed by `file_not_found` — evidence
it had no source-level knowledge of the component, not that it edited it.

So retention, computed against the reference patch's `files_modified`, mis-measures context
adequacy wherever a task admits more than one solution layer. This is a flaw in the WP12
retrieval-side metric, **not** a harness defect, and unlike anomaly A it does **not** move a pass
count: those 3 passes are already inside the 18.

### The rule this work must not break

**The applier, the harness and every condition TOML stay untouched.** All-or-nothing must remain
exactly as published or WP5 comparability breaks. Step 9 changes the *input*, never the code.

---

## What is already verified (read-only, during planning)

| Fact | Value |
|---|---|
| Corpus: 8 runs (6 WP5 + 2 WP12) | **420** candidates, all `output_format = search_replace` |
| Grades | 259 passed, 112 never_applied, 38 test_fail, 11 build_fail; **0 quarantined, 0 harness_error** |
| `never_applied` reasons | `search_not_found` 59, `file_not_found` 48, `malformed_blocks` 5 |
| Passing candidates editing **none** of `files_modified` | **6**, all P6 / `bm25_matched` / `category.ts` |
| `AppSidebar/CategoryList.tsx` at the pinned commit | **does not exist** |

A read-only prototype also measured **52 of 112** `never_applied` candidates as having ≥1 edit that
would apply, 40 of them touching a retrieved file. **Provisional** — step 8 must re-derive it and
gate on it, not inherit it.

---

## Design decisions

- **Three measurements from artifacts, then one counterfactual through the real harness.** Step 8
  needs no Docker and no API; step 9 needs Docker and no API. Step 8 is a standalone deliverable.
- **Mirror the applier, never replace it.** A Python transliteration of `apply_edits.js` is the
  only way to ask "which edits would have applied" over 420 candidates. It is licensed by a
  **differential gate**: its predicted first failure must equal the recorded `apply_reason` for
  every candidate. The JS stays normative and unmodified.
- **Corrected retention is a boolean sufficiency test, not a fraction.** *Does the retrieved set
  contain some witnessed passing solution?* A witnessed solution is the edited-file set of any
  passing candidate in the corpus, minus paths absent at the pinned commit (so P3's created file
  drops out, matching `wp12_matched_retrieval_diag.py`). A union of edited files is **not** a
  requirement set: for P6 it would score 1/2 and say nothing.
- **Witnessed sufficiency is survivorship-biased by construction** — a solution is only witnessed
  because some arm happened to retrieve it. It is therefore a *lower bound on adequacy*, and that
  belongs in the generated table's preamble, not only in the note.
- **The counterfactual never merges into a pass rate.** Separate stem, separate `run_id`, its own
  directory under `.cache/`, and a boxed disclaimer as the first thing in the generated table.
- **`context_files()` parses the prompt, not the metadata.** `kg_augmented` and `whole_file` have
  no `included_files` key at all, so the rendered `#### Name (path)` headers are the only uniform
  record of what a model was shown.

---

## Steps

**8. Corpus-wide measurement** — `scripts/wp12_apply_loss_report.py`, new module
`src/evaluation/edit_replay.py`, tests in `tests/unit/evaluation/test_edit_replay.py`.

- **M1 — all-or-nothing loss.** Among `never_applied` candidates, how many had ≥1 edit whose SEARCH
  matches the pristine source exactly once, and how many of those edits targeted a **retrieved**
  file. Per model × condition × task.
- **M2 — solution-layer divergence.** Among **passing** candidates, how many edited none of the
  task's `files_modified`.
- **M3 — corrected retention.** WP12's retention table with a `sufficient` column beside the
  published fraction, flipped cells marked.

  Writes `wp12_apply_loss.{md,csv}` — one CSV, three row kinds under a `metric` column so the three
  measurements cannot drift apart — and `.cache/wp12_apply_loss/replay_plan.json`, carrying a
  sha256 of each `results.jsonl` so step 9 cannot run against a corpus that has moved.

  `edit_replay.py` transliterates `main()` in `apply_edits.js`, differing in exactly one respect:
  record a verdict and continue instead of aborting. Two behaviours are load-bearing — the **staged
  body** (a second edit to the same file sees the first's output; a *skipped* edit contributes
  nothing) and `locate()`'s **single trailing-newline retry**.

  Reuse, never re-derive: `outcomes.grade` / `SCALE` / `EXCLUDED`, `harness.tasks.load_pilot_task`
  (for `git_commit`), `orchestrator.resolve_repo_root` and `_load_task_yaml`,
  `docker_build.verify_pinned_commit`, `edit_formats.base.EditScript`.

**9. Per-edit replay counterfactual** — `scripts/wp12_per_edit_replay.py` → `wp12_per_edit_replay.{md,csv}`.

For each candidate M1 identifies, rebuild an edit script containing only the accepted edits — via
`EditScript.to_json()`, never hand-rolled — and run it through `run_candidate`. Safety envelope,
**asserted before the first Docker call**, not commented:

- `results_dir = .cache/wp12_replay_results` (gitignored) **and** a fresh `run_id`:
  `_write_harness_result` *appends* to `results.jsonl`, and `harness_results/` is git-tracked;
- candidate ids prefixed `replay__<leg>__<run>__…`, asserted disjoint from every real id —
  `run_candidate` does `shutil.rmtree` on `.cache/harness_runs/<candidate_id>/`, keyed on the id
  **alone**, so a real id would wipe a live scratch dir;
- timeouts from `load_timeouts()`, **never** `calibrate_timeouts`, which writes
  `conditions/timeouts.toml`;
- rebuilding with **all** indices must reproduce the original `diff.patch` byte-for-byte, proving
  the reduction is a pure subset and not a re-serialisation artefact;
- every replay must return `apply_mode == "exact_unique"`. Anything else means the Python mirror
  and the Node applier disagree — abort loudly rather than record a zero.

`floor`, `whole_file` and `kg_augmented` replays go in **their own section**. The floor arm's 0/30
is the most load-bearing number in WP5; any movement must be impossible to miss.

**10. The note and the corrections** — `wp12_anomalies.md`, plus edits to
[`wp12_matched_context.md`](wp12_matched_context.md).

Two passages there are now **wrong** and must change in the same commit:

- *"Six of ten candidates repaired a file they were never shown"* — they repaired `category.ts`, a
  different file at a different layer, and the one candidate that reached for the component invented
  a non-existent path;
- *"In 11 of the 12 cells, retention is the outcome"* — the exceptions move under corrected
  retention.

**The note must not overclaim.** Only step 9 can widen the bound on 18. M2/M3 justify a different
sentence — that retention under-reports adequacy on 2 of 12 matched cells — and must not be written
as if they move a pass count.

---

## Verification

1. **Differential gate** (the one that licenses a Python mirror of a Node applier). For all 420
   candidates, the simulator's predicted first failure equals the recorded `apply_reason`, and
   "no failure" equals `stage != diff_apply_fail`. Runs on every invocation; exits non-zero on any
   mismatch.
2. **Round-trip gate.** Every `diff.patch` rebuilt from its own JSON is byte-identical.
3. **Retrieved-set gate.** Per-candidate `included_files` agrees across a cell's 5 candidates and
   with `wp12_matched_retrieval.csv`.
4. **Pin gate.** `verify_pinned_commit` on both repos before any `git show`.
5. **Replay gate.** Every step-9 replay returns `apply_mode == "exact_unique"`.
6. **Published-artifact gates**, re-run after all commits: `wp5_outcome_report.py`,
   `wp12_matched_report.py` and `wp12_matched_retrieval_diag.py` all regenerate with **no diff**
   (and `api_calls == 0`); `git status --porcelain harness_results/ candidate_artifacts/
   experiment_logs/ conditions/` **empty**; `git diff --stat docker/ src/harness/ conditions/base/`
   **empty**.
7. **Unit suite** green (708 today, plus the new tests).
8. **Numbers the report must reproduce**, so a regression is visible: 420 candidates; 112
   `never_applied`; 6 disjoint passes, all P6 / `bm25_matched`; M3 flips exactly P2/dense@matched
   and P6/bm25@matched.

---

## Commits

```
docs(anomaly)  WP12 steps 8-9 plan
feat(anomaly)  edit_replay: read-only mirror of apply_edits.js + unit tests
exp(anomaly)   apply-loss report (M1/M2/M3) + wp12_apply_loss.{md,csv}
exp(anomaly)   per-edit replay counterfactual + wp12_per_edit_replay.{md,csv}
docs(anomaly)  WP12 anomalies note + corrections to wp12_matched_context.md
```

**Cost:** zero API. Step 9 is ~52 Docker runs, sequential, 30–60 min wall clock (TakeNote tasks are
calibrated at 146–175 s, react-shopping-cart at 10–13 s). Both images already exist.

## Risks

| Risk | Fallback |
|---|---|
| The Python mirror drifts from `apply_edits.js` | The differential gate runs over all 420 candidates on every invocation, and step 9 cross-checks 52 of them against the real applier in Docker. The JS is named normative in the module docstring. |
| Step 9 writes into `harness_results/` | Three assertions before the first Docker call, a fresh `run_id`, `.cache/` is gitignored, and gate 6's `git status` check proves it after the fact. |
| A replay wipes a real candidate's scratch dir | `replay__<leg>__<run>__` prefix, asserted disjoint from the real id set. |
| The counterfactual leaks into a pass rate | Separate stem, separate `run_id`, separate directory; neither report script is edited and both enumerate their sources explicitly; boxed disclaimer first in the generated table. |
| Corrected retention is read as a neutral re-measurement | Survivorship caveat in the table preamble, the note, and the CSV column documentation. |
| Step 9 slips past the window | Step 8 is standalone: M1/M2/M3 already resolve anomaly B and half of anomaly A, and the note ships with the bound stated as a candidate count rather than a pass count. |
| The floor arm moves under per-edit application | Reported in its own section, never in the ablation tables. |
