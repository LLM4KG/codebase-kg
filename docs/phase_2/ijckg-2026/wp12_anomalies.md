# WP12 steps 8–9 — The two anomalies, resolved

> Written 21 Sep 2026. Plan: [`wp12_anomalies_plan.md`](wp12_anomalies_plan.md). Generated
> tables: [`wp12_apply_loss.md`](wp12_apply_loss.md) (M1/M2/M3, no Docker) and
> [`wp12_per_edit_replay.md`](wp12_per_edit_replay.md) (the counterfactual, 52 Docker runs).
> Scripts: `scripts/wp12_apply_loss_report.py`, `scripts/wp12_per_edit_replay.py`; the applier
> mirror is `src/evaluation/edit_replay.py`. Zero API spend.
> The note this corrects: [`wp12_matched_context.md`](wp12_matched_context.md).

[`wp12_matched_context.md`](wp12_matched_context.md) closed with two cells it could not
explain. Both are now explained, and the explanations pull in opposite directions: one
**narrows** a caveat WP12 shipped with, the other **weakens** a claim WP12 made. Both belong
in the paper.

## Summary

1. **Anomaly A was the applier, and it costs exactly one cell.** `docker/apply_edits.js` is
   all-or-nothing, so WP12's matched totals were published as upper bounds on the damage a
   thin context did. Replaying the survivors per-edit shows three of the four totals do not
   move at all. Only Claude dense @matched moves, 15 → 20, and only on P2.
2. **Anomaly B was the metric, and it costs a claim.** Retention measured against the
   reference patch's `files_modified` mis-measures adequacy wherever a task admits more than
   one solution layer. Corrected, WP12's "retention is the outcome in 11 of 12 cells" becomes
   **8 of 12**.
3. **A passage in `wp12_matched_context.md` was simply false** and is corrected below: nobody
   repaired a file they were never shown.
4. **Nothing published changes.** No pass count moves, no cell of WP5 or WP12 is rewritten,
   and the applier, the harness and every condition TOML are byte-identical.

---

## Anomaly A — the applier, not the model

**The cell.** P2 at `text_emb_3_large_matched`: an identical 1,497-token context, Claude
**0/5** and Qwen **5/5**. Retrieval is model-independent, so the two legs saw the same four
files — `note.ts` among them, `containers/NoteList.tsx` and `resources/TestID.ts` not.

**The mechanism.** `docker/apply_edits.js` stages edits in memory and flushes only once every
one of them resolves; a single failed SEARCH aborts the whole script. That is right for the
harness — a half-applied script produces build errors describing a state the model never asked
for, which is the failure `recount_c0` was quarantined for. But for *measurement* it collapses
"three of four edits were correct" into `never_applied`.

Claude attempted the full reference-shaped fix: two edits on the retrieved `note.ts`, two on
the unretrieved `NoteList.tsx`. Qwen attempted `note.ts` only. Replaying Claude's SEARCH blocks
against the pinned tree:

| candidate | edits that would apply | of 4 | the `NoteList.tsx` edits |
|---|---|---|---|
| n1 | `note.ts` ×2, `NoteList.tsx` ×1 | **3** | one bad SEARCH |
| n2 | `note.ts` ×2 | 2 | both bad |
| n3 | `note.ts` ×2, `NoteList.tsx` ×1 | **3** | one bad SEARCH |
| n4 | `note.ts` ×2 | 2 | both bad |
| n5 | `note.ts` ×2 | 2 | both bad |

**Both `note.ts` edits would have applied in all five** — which is exactly the pair Qwen passed
with. n1 and n3 also reconstructed a correct `NoteList.tsx` hunk without ever seeing the file.
So Claude's 0/5 was never a failure to solve P2; the applier discarded a correct reducer fix
because the model *also* attempted the part its context did not cover.

### How wide the artifact is

That reasoning generalises, so it was measured rather than assumed. Over the whole
420-candidate WP5 + WP12 corpus (`wp12_apply_loss.md`):

| | |
|---|---|
| never-applied candidates | **112** |
| …with ≥1 edit the applier would have accepted | **52** |
| …of those, ≥1 edit changing a file that already existed | **42** |

The narrowing in the last row matters: a `write` creates a file and can only fail on a path
that escapes the repo, so it survives almost by definition. P3's `floor` candidates all
"survive" by creating `useCopyToClipboard.ts` and then failing to wire it in — none of their
*fix* survives. Counting those as apply-loss would overstate the artifact.

### What the counterfactual actually says

All 52 were rebuilt with only their accepted edits and sent through the **unmodified**
`run_candidate`, applier and images (`wp12_per_edit_replay.md`). **9 of 52 would have passed.**
All-or-nothing discarded a *working* fix nine times and a broken one forty-three times.

| Model | Arm | Published /30 | Counterfactual /30 |
|---|---|---|---|
| Claude | `bm25_matched` | 18 | 18 |
| Claude | `text_emb_3_large_matched` | 15 | **20** |
| Qwen | `bm25_matched` | 15 | 15 |
| Qwen | `text_emb_3_large_matched` | 18 | 18 |

**Three of the four matched totals do not move.** For Claude BM25 and both Qwen matched arms,
"upper bound on the damage" and "measurement of the damage" turn out to be the same number.
The caveat WP12 shipped with narrows from all four totals to one cell — and that cell is the
anomaly that prompted the work, where per-edit application gives exactly Qwen's 5/5 by exactly
Qwen's edits.

Two guards on reading that table:

- **The floor arm does not move.** 0/30 on both legs under per-edit application too. WP5's
  most load-bearing number is not an artifact of the applier.
- **It is not a baselines-only effect.** On Qwen the oracle gains 2 (17 → 19), the KG arm 1
  (16 → 17) and BM25 @7,000 1 (22 → 23). Per-edit application is not a thumb on the scale for
  one side of the comparison.

### What to write in the paper

WP12's matched totals stand as published. The dense-matched figure for Claude carries one
sentence of qualification — that under per-edit application it would be 20 rather than 15,
because the all-or-nothing applier discards partially-correct scripts — and the other three
carry none, because they do not move. The counterfactual is never quoted alone and never added
to a pass rate: a partial fix that happens to satisfy a behavioural test is not the same result
as a complete one.

---

## Anomaly B — the metric, not the harness

**The cell.** P6 at `bm25_matched`: the reference target `containers/CategoryList.tsx` was
retained **0/1**, yet **3/5 passed on each leg**.

### The correction

`wp12_matched_context.md` said *"Six of ten candidates repaired `CategoryList.tsx` without ever
being shown it."* **That is false.** All ten candidates edited `src/client/slices/category.ts`,
a file BM25 *did* retrieve, at the reducer layer — which `P6.yaml` explicitly blesses as a valid
solution. Nobody edited `containers/CategoryList.tsx`. One candidate (Claude n1) additionally
emitted an edit for `src/client/components/AppSidebar/CategoryList.tsx`, **a path that does not
exist** at the pinned commit — the real file is under `containers/` — and was killed by
`file_not_found`. That is evidence the model had *no* source-level knowledge of the component,
which is the opposite of what the sentence claimed.

So this is not a case of a model repairing something it could not see. It is a case of the
metric asking the wrong question.

### The metric

Retention asks *is every file the reference patch edited still in the context?* Where a task
admits more than one solution layer, that mis-measures adequacy. M3 asks instead: **does the
retrieved set contain some witnessed passing solution?** — a witnessed solution being the
edited-file set of any passing candidate in the corpus, minus paths absent at the pinned commit
(so P3's created file drops out, matching `wp12_matched_retrieval_diag.py`).

Two properties of that test have to travel with it:

- It is **survivorship-biased by construction**. A solution counts as witnessed only because
  some arm happened to retrieve enough to find it. `sufficient = False` means "no *known*
  solution fits", never "no solution exists". It is a **lower bound on adequacy**.
- It is **not a predictor of passing**, and the data says so loudly — see below.

**Five of 24 cells flip**, all in the same direction (published retention said inadequate, a
witnessed solution says adequate): `P2/dense@7000`, `P2/dense@matched`, `P4/bm25@matched`,
`P4/dense@matched`, `P6/bm25@matched`. None flips the other way, which is what makes this a
correction to the metric rather than a different metric.

> The plan predicted **two** flips, both at the matched budget. It was written before witnessed
> solutions were computed corpus-wide and was wrong: there are five, and one is a *published*
> cell. The five are now a named regression gate in `wp12_apply_loss_report.py`.

### What this costs WP12

`wp12_matched_context.md` called the retention–outcome correspondence *"the tightest evidence
in this work package"*, at **11 of 12** Claude matched cells. Corrected, it is **8 of 12**:

| | correspondence | exceptions |
|---|---|---|
| published retention | 11 / 12 | P6/BM25 |
| corrected retention | **8 / 12** | P4/BM25, P4/dense, P2/dense, P6/BM25 |
| corrected retention, per-edit applier (counterfactual) | 9 / 12 | P4/BM25, P4/dense, P6/BM25 |

The three durable exceptions are the interesting ones, and they all say the same thing:
**a sufficient context is not a sufficient condition for a pass.** P4's matched cells carried
the complete `Cart.tsx` (82 lines) and `useCart.ts` (33 lines) — verbatim, whole files, the
exact pair a passing Qwen candidate used at 7,000 tokens — and Claude still scored 0/5 on both,
with the per-edit replay confirming `test_fail` rather than an applier artifact. The files were
there; the models did not use them.

That is a weaker claim than WP12 made, and the weaker claim is the true one. The defensible
sentence is: *at a matched budget, losing the target file reliably costs the cell, but keeping
it does not reliably win it.*

---

## What changes in `wp12_matched_context.md`

Two passages, corrected in the same commit as this note:

1. *"Six of ten candidates repaired `CategoryList.tsx` without ever being shown it"* → they
   repaired `category.ts`, a different file at a different layer, and the one candidate that
   reached for the component invented a path that does not exist.
2. *"In 11 of the 12 cells, retention is the outcome … the tightest evidence in this work
   package"* → 8 of 12 under corrected retention, with the three durable exceptions named.

The anomalies section itself is replaced by a pointer here, since both anomalies are now closed.

## What does not change

- **Every published number.** WP5 and WP12 regenerate byte-identically; `git status` over
  `harness_results/`, `candidate_artifacts/`, `experiment_logs/` and `conditions/` is empty.
- **The applier, the harness and every condition TOML.** `git diff` over `docker/`,
  `src/harness/` and `conditions/base/` is empty. All-or-nothing stays exactly as published —
  changing it would break WP5 comparability across every condition, and the replay is evidence
  *about* it, not an argument to replace it.
- **The headline.** On Claude the WP5 ordering is still an artefact of budget; on Qwen it is
  still not a sweep. Neither anomaly touched either statement.

## What a reviewer could still ask

- **"Why trust a Python mirror of a Node applier?"** Two gates. The mirror's predicted first
  failure equals the recorded `apply_reason` for **all 420** candidates, 0 mismatches, re-run on
  every invocation; and all **52** replays came back `apply_mode = exact_unique` from the real
  Node applier in the real images.
- **"Does witnessed sufficiency smuggle in hindsight?"** Yes, and deliberately — it is stated
  as a lower bound in the generated table's preamble, in the CSV column documentation and here.
  A retriever is never penalised for missing a solution nobody found.
- **"Is 9 of 52 enough to conclude anything?"** It is enough for the claim made: three of four
  matched totals are unmoved, so the published figures are measurements and not bounds. The
  per-cell counterfactuals are n=5 at temperature 0 and are not significance claims.

## Artifacts

| | |
|---|---|
| M1 / M2 / M3 tables | [`wp12_apply_loss.md`](wp12_apply_loss.md), `.csv` (714 rows, three row kinds under a `metric` column) |
| the counterfactual | [`wp12_per_edit_replay.md`](wp12_per_edit_replay.md), `.csv` |
| the applier mirror | `src/evaluation/edit_replay.py` + 28 unit tests (suite 708 → 736) |
| raw replay results | `.cache/wp12_replay_results/wp12_per_edit_replay_counterfactual` (gitignored) |
| cost | **zero API**; 52 Docker runs, ~45 min sequential |
