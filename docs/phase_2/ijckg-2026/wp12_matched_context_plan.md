# WP12 — Context-budget-matched ablation: implementation plan

> Written 20 Sep 2026. Planned for the extended implementation window (to 26 Sep), ahead of the
> 23–28 Sep writing leg. Referenced from §2 of
> [`revision_implementation_plan_18-22Sep.md`](revision_implementation_plan_18-22Sep.md).
> Supersedes nothing: every WP5 artifact stays exactly as published.
>
> **Revision — 21 Sep 2026.** Re-checked against the post-WP8 tree (HEAD `9969dee`) before
> implementation. The design, the per-task budgets, the run shape, the cost estimate and the
> framing all survived unchanged; **four passages did not** and are corrected in place, each marked
> with the date and the reason:
>
> 1. *Hazard to close on the way* → **already closed by WP8** on 21 Sep. The section is retitled and
>    the matching step-3 bullet dropped.
> 2. *"All six base TOMLs set `retriever == condition_id`"* → there are now **seven**, and
>    `kg_augmented_hardened.toml` sets `retriever = "kg_augmented"`. The keying change is therefore
>    no longer a pure no-op — it is what makes that condition dispatch.
> 3. *Step 3* → the keying change now touches WP8's `KG_CONDITIONS`, the generation-test fake and
>    two WP8 tests. Not foreseen on 20 Sep; the blast radius is now spelled out.
> 4. *Step 1, "prototyped already"* → no such script exists, tracked or untracked.
>    `scripts/wp3_recall_diagnostic.py` is the thing to extend.
>
> Two design points were decided in the same round: the missing-budget **raise** (step 4) and the
> **post-WP12 WP8 revisit** at the end of this file.

## Context

The WP5 comparison is confounded by context length. The KG-augmented condition retrieves
**371–1,532 tokens** per task; BM25 and dense fill to **4,602–6,981**:

| Task | KG | BM25 | dense | whole-file (oracle) |
|---|---|---|---|---|
| P1 | 626 | 5,635 | 5,905 | 278 |
| P2 | 1,532 | 6,962 | 6,938 | 2,611 |
| P3 | 772 | 6,964 | 6,919 | 709 |
| P4 | 371 | 4,949 | 5,905 | 599 |
| P5 | 497 | 4,602 | 5,905 | 289 |
| P6 | 841 | 6,899 | 6,981 | 699 |

So "BM25 30/30 vs KG 25/30" (Claude) and "dense 23/30 vs KG 16/30" (Qwen) compare retrieval quality
**and** budget at once, and a reviewer can say so. Ground rule 2 fixes the *cap* at 7,000 tokens for
every condition, but the KG never approaches it, so the **realised** context differs by 4–13×.

The oracle shows the extra budget is not what wins: it passes **30/30** on Claude using 278–2,611
tokens, at or below the KG's size on four of six tasks. Small correct context suffices; the
baselines spend 5–10× to find it.

WP12 removes the confound by re-running BM25 and dense capped at exactly the KG's per-task context,
and reports **both** views — the 7,000-token comparison (realistic deployment) and the matched one
(isolates selection quality from budget). It answers the question the paper needs: *is the KG's
value what it selects, or only that it is cheap?*

It touches no graph, no annotation file and no schema count, so WP6 annotation can start immediately
and run in full alongside it. WP11 (Redux) stays deferred —
[`wp11_redux_schema_plan.md`](wp11_redux_schema_plan.md).

### Evidence already gathered (20 Sep, zero API cost — every embedding was a cache hit)

**Feasibility, no degeneracy.** 54 of 55 react-shopping-cart files and 56 of 60 TakeNote files fit
inside their task's matched budget individually, so a matched arm is never forced to return nothing.

**Target-file retention** — at the matched budget, does the baseline still see the file the
reference patch edits?

| Task | BM25 @7000 | BM25 @matched | dense @7000 | dense @matched |
|---|---|---|---|---|
| P1 | ✓ | ✓ | ✓ | ✓ |
| P2 | 3/3 | **1/3** (only `TestID.ts`) | 2/3 | **1/3** (only `note.ts`) |
| P3 | ✓ | ✓ | ✓ | ✓ |
| P4 | 3/3 | **2/3** | 3/3 | **2/3** |
| P5 | 2/2 | 2/2 | 2/2 | **1/2** |
| P6 | ✓ | **✗ dropped** | ✓ | ✓ |

P3's `useCopyToClipboard.ts` is created by the task, so it is unretrievable by construction and
excluded from the counts. P6 is the sharpest case: `CategoryList.tsx` is 669 tokens against an 841
budget, so it *fits* — BM25's ranking simply put five other files ahead of it, a ranking failure the
7,000-token cap was hiding.

**Prediction, recorded before the runs:** the KG's relative position improves on P2, P4 and P6.

---

## What is preserved

The 7,000-token experiment stays intact and becomes the headline row of the WP12 report. For P1 that
means KG 626 / BM25 5,635 / dense 5,905 / oracle 278 is still reported, with the matched row beside
it. Guaranteed by four mechanisms, not by care:

1. **The WP5 results are finished artifacts on disk** and are never re-run. WP12 writes to new run
   ids (`*_wp12_matched`), and `RunIdInUseError` refuses to start on an existing id.
2. **New condition files.** `conditions/base/bm25.toml` and `text_emb_3_large.toml` are untouched
   and still cap at 7,000; the matched conditions are separate files.
3. **`scripts/wp5_outcome_report.py` is not edited**, and regenerating `wp5_outcomes.{md,csv}` with
   **no diff** is a verification gate. If the dispatch change perturbs anything, this fails.
4. **Both views in one table**, matched against unmatched, per model × condition × task.

The only shared code that changes is the orchestrator dispatch and the dense-key preflight; both
affect future runs only and cannot reach results already written. The oracle stays **uncapped** in
both views — capping it would stop it being an upper bound (ground rule 2).

---

## Design decisions

- **Per-task budgets, from the KG's own measured context:** P1 626, P2 1,532, P3 772, P4 371,
  P5 497, P6 841. Verified near-deterministic — 11 of 12 (task × leg) cells have a single distinct
  `retrieval_token_count` across all five candidates; the exception is P2/Qwen (1,532 ×3, 1,552 ×2,
  median 1,532, a 1.3% spread). The per-task median is identical for both legs, so one table serves
  both.
- **Budgets are generated, not typed.** A script reads `wp5_outcomes.csv` and writes the two
  condition TOMLs. Same discipline as the WP9 statement bullets: no hand-entered claims.
- **Dispatch on `cfg.condition.retriever`, not `cand.condition`** *(argument restated 21 Sep)*.
  `RetrievalConditionConfig.retriever` exists (`src/retrieval/config.py:28`) and is still **read
  nowhere in `src/`** — re-verified at `9969dee`. Six of the seven base TOMLs set
  `retriever == condition_id`; the seventh, `kg_augmented_hardened.toml` (WP8), sets
  `retriever = "kg_augmented"`, and is the first real case of the two diverging. That makes the
  field load-bearing rather than hypothetical: keying on it lets `bm25_matched.toml`
  (`retriever = "bm25"`) dispatch with **no new branch**, and lets WP8's `KG_CONDITIONS` name tuple
  be deleted rather than joined by two more like it. The cost — three call sites and two WP8 tests
  — is itemised in step 3.
- **`token_budget` needs no retriever change.** It is already a constructor kwarg on `BM25Retriever`
  (`src/retrieval/bm25_retriever.py:161`) and `DenseRetriever` (`src/retrieval/dense_retriever.py:172`).
  The orchestrator resolves it from `retriever_params` and passes it.
- **Framing: an ablation, not a sixth baseline.** Nobody deploys BM25 at 371 tokens. The note and
  the paper must say "context-budget-matched ablation" and always report the 7,000-token table
  alongside.
- **No new runs for floor, whole-file or KG.** They are unchanged and reused from WP5.

### Hazard already closed (WP8, 21 Sep — was "Hazard to close on the way")

As written on 20 Sep, `run_one_candidate`'s dispatch ended in `else: FloorRetriever(...)`, so **any
condition without a branch silently ran as floor** — an empty context that would read as a
catastrophic result rather than a wiring bug, and a whole leg quietly wasted.

**WP8 hit the same hazard first** and fixed it while wiring `kg_augmented_hardened`, which would
otherwise have run as floor under its own name. `src/generation/orchestrator.py:388-399` now ends
in an explicit floor case plus

```python
raise ValueError(f"no retriever is wired for condition {cand.condition!r}; …")
```

pinned by `test_a_condition_with_no_retriever_raises_instead_of_running_as_floor`
(`tests/unit/generation/test_orchestrator.py:332`). WP12 inherits the fix and only has to keep the
`raise` intact when it re-keys the chain on the retriever — see step 3.

---

## Steps

**0. Record the plan.** This file, linked from the revision plan. Commit alone — `docs(matched)`.

**1. Retrieval-side diagnostic, no generation.** `scripts/wp12_matched_retrieval_diag.py`: per task,
run BM25 and dense at 7,000 and at the matched budget; report corpus size, files included, tokens
used, and which reference-patch files survive. Must assert
`metadata["api_calls"] == 0` (`src/retrieval/dense_retriever.py:253`, surfaced via `**stats`) so a
cache miss cannot silently bill. Writes `wp12_matched_retrieval.{md,csv}`. **A deliverable on its
own** — if the generation runs slip, this table still answers the confound question.

*Corrected 21 Sep:* this plan said "prototyped already". No such script exists — nothing matching
`wp12*` is in `scripts/`, tracked or untracked, and there is no other worktree. The 20 Sep numbers
in the evidence table above were produced by a throwaway that was not kept. **Extend
`scripts/wp3_recall_diagnostic.py` instead of starting from a blank file:** it already uses the
orchestrator's own `load_task_spec` / `_load_task_yaml` / `resolve_repo_root`, constructs both
retrievers from literal `RetrievalConditionConfig`s, and reads the same `ranked_top` /
`included_files` / `budget_tokens_used` metadata. Two gaps to close — it reads only
`files_modified` (step 1 also needs `files_created`, for P3's `useCopyToClipboard.ts`) and it
prints to stdout instead of writing files.

**2. Budget table + conditions.** `scripts/wp12_make_matched_conditions.py` reads `wp5_outcomes.csv`,
takes the per-task median `context_tokens_median` for `kg_augmented`, asserts both legs agree, and
writes:
- `conditions/base/bm25_matched.toml` — `condition_id = "bm25_matched"`, `retriever = "bm25"`,
  `[retriever_params] token_budget_by_task = { P1 = 626, … }`, with a provenance header comment;
- `conditions/base/text_emb_3_large_matched.toml` — same, `retriever = "text_emb_3_large"`, keeping
  `embedding_model`.

**3. Wiring** (`src/generation/orchestrator.py`, `src/generation/cli.py`, and — *added 21 Sep* —
`tests/unit/generation/conftest.py`). The bare-`else` bullet is gone: WP8 did it.

- `KNOWN_CONDITIONS` += `bm25_matched`, `text_emb_3_large_matched` (**not** in default `CONDITIONS`).
  WP8's `kg_augmented_hardened` is already in it and not in `CONDITIONS` — the same pattern, and the
  precedent to follow.
- **Dispatch keyed on `cfg.condition.retriever`.** The `raise` at the end of the chain stays; only
  the thing being matched changes, and its message should name the retriever as well as the
  condition.
- **`KG_CONDITIONS` is deleted** (`src/generation/orchestrator.py:72`), not extended. WP8 introduced
  it, and leaving it beside a `BM25_CONDITIONS` and a `DENSE_CONDITIONS` would mean three name
  tuples to keep in sync with seven-plus TOMLs. Three call sites:

  | Line | Today | After |
  |---|---|---|
  | 345 | `if cand.condition in KG_CONDITIONS and not mock_retrieval:` | `if retriever == "kg_augmented" and not mock_retrieval:` |
  | 388 | `elif cand.condition == "floor" or cand.condition in KG_CONDITIONS:` | `elif retriever in ("floor", "kg_augmented"):` |
  | 590 | `any(c.condition in KG_CONDITIONS for c in group)` — the per-project Memgraph load gate | the same test on `load_experiment_config(c.run_name, c.condition).condition.retriever` |

  Line 590 sits in the project-grouped run loop, where no config is loaded yet. Resolve it through
  `load_experiment_config` rather than a new TOML reader, so it goes through the same seam the unit
  tests monkeypatch.
- **The generation-test fake must learn the real map.** `tests/unit/generation/conftest.py`'s
  `fake_load_experiment_config` builds
  `RetrievalConditionConfig(condition_id=condition_name, retriever=condition_name)`. Under
  retriever-keying, `kg_augmented_hardened` would then resolve to a retriever of that name, match no
  branch and **raise**, breaking WP8's
  `test_hardened_kg_condition_dispatches_to_the_kg_retriever`. Give the fake a small
  condition → retriever dict defaulting to identity, mirroring the TOMLs. Without this the keying
  change looks like it broke the hardened condition when it only broke the stand-in.
- Both baseline branches resolve
  `cfg.condition.retriever_params.get("token_budget_by_task", {}).get(cand.task_id)` and pass
  `token_budget=`; a **missing entry raises** — see step 4.
- `_preflight_dense_key` (`src/generation/cli.py:51-63`) still tests the literal
  `"text_emb_3_large"` — re-verified 21 Sep — so it must also catch `text_emb_3_large_matched`, or a
  cold cache turns every candidate into a `harness_error` and spends the run id.

**4. Tests** (`tests/unit/retrieval/test_bm25_retriever.py`, `…/test_dense_retriever.py`,
`tests/unit/generation/test_orchestrator.py`):
- a matched-budget retrieve renders a context ≤ the task's budget and `metadata.token_budget` equals
  it;
- **all seven existing conditions dispatch to the same retrievers as before the keying change**
  (the regression guard) — seven, not six, because `kg_augmented_hardened` is the one whose
  `retriever` differs from its `condition_id` and so the one the change could actually break;
- an unknown retriever **raises** instead of falling through to floor — WP8's test at
  `test_orchestrator.py:332` already covers this; re-point it at the retriever, keeping the
  `match="no retriever is wired"` assertion working;
- `test_orchestrator.py:321`'s `set(orch.KG_CONDITIONS) == {…}` assertion is **rewritten**, since
  the tuple is gone: assert instead that `kg_augmented_hardened` dispatches to the KG retriever
  because its TOML says `retriever = "kg_augmented"`;
- `bm25_matched` / `text_emb_3_large_matched` dispatch to the right class with the per-task budget;
- **a task absent from `token_budget_by_task` raises** *(decided 21 Sep; reverses this plan's
  original "falls back to `DEFAULT_TOKEN_BUDGET`")*. A candidate recorded under a `*_matched`
  condition must never be able to have run at 7,000 tokens: that is WP8's silent-floor defect in a
  new costume — an arm labelled one thing and behaving as another, invisible except in a token
  count. Step 2's generator writes all six tasks, so the raise is a guard, not a code path.

**5. Runs.** New run ids; pilot and WP5 results untouched:

```
uv run pipeline pilot run --run claude_primary  --conditions bm25_matched,text_emb_3_large_matched \
    --n 5 --run-id claude_primary_2026-09-2X_wp12_matched
uv run pipeline pilot run --run qwen_robustness --conditions bm25_matched,text_emb_3_large_matched \
    --n 5 --run-id qwen_robustness_2026-09-2X_wp12_matched
```

120 candidates (2 conditions × 6 tasks × n=5 × 2 models). **Under $2** — context is ~5× smaller than
the runs already paid for. **2–4 hours** of harness wall-clock. Dense embeddings are cache hits.

**6. Report.** `scripts/wp12_matched_report.py` → `wp12_matched.{md,csv}`: the graded scale per
model × condition × task, matched against unmatched, with context tokens actually used, USD per
candidate, and the step-1 retention table. **Do not extend `scripts/wp5_outcome_report.py`** — it
asserts an exact cell matrix and exits on an unexpected condition
(`scripts/wp5_outcome_report.py:71-72`); WP5's published artifact must keep regenerating
byte-identically.

**6b. Regenerate the WP9 cost tables** *(added 21 Sep)*. `scripts/wp9_phase2_cost.py` prices the six
WP5 runs from an explicit `WP5_RUNS` list, which the matched runs cannot disturb — but its second
section, *"All Phase 2 runs, per day, model and provider"*, **globs `experiment_logs/`**
(`phase2_runs()`, `scripts/wp9_phase2_cost.py:160`). The matched runs therefore add day rows and
move its grand total. Re-run it after step 5, name the new rows as WP12's, and check that the
18–19 Sep reconciliation bullets — which are pinned to those two days — still read true. Nothing
about WP5's own cost changes; only the all-runs dashboard cross-check grows.

**7. Fold into WP10** `results_summary.md`, and update this plan's WP list and the deliverables
checklist.

---

## Verification

- `uv run pytest tests/unit -q` green, including the dispatch regression guard.
- `uv run python scripts/wp5_outcome_report.py` regenerates `wp5_outcomes.{md,csv}` with **no diff**
   — proves the keying change did not disturb the published WP5 artifact.
- Step 1 reports `api_calls == 0` for every dense call.
- Per-candidate `metadata.json`: `retrieval_token_count` ≤ the task's matched budget and within a
  few percent of the KG's value for that task (spot-check P4 at 371).
- No candidate in the matched run has an empty context (the floor-fallback signature).
- `harness_results/` and `candidate_artifacts/` gain only the two new run ids; `git status` shows no
  modification under any WP5 run directory.
- *(added 21 Sep)* `git diff --stat` shows **no change** under
  `conditions/base/{bm25,text_emb_3_large,kg_augmented}.toml`. The published arms' budgets are the
  one thing an ablation about budgets must not touch, and the matched conditions are separate files
  precisely so this check can be mechanical.
- *(added 21 Sep)* `PIPELINE_DB__URI=bolt://localhost:7688 uv run python
  scripts/wp8_anchor_robustness.py` still reproduces 626 / 1,532 / 772 under `strict` and exits
  zero. It loads its two conditions through `load_experiment_config` and dispatches through the
  same chain WP12 re-keys, so it is the WP8-side equivalent of the `wp5_outcomes.md` no-diff gate.
  Needs the scratch Memgraph up.

## Commits

```
docs(matched)  WP12 plan
docs(matched)  reconcile the plan with the post-WP8 tree        # 21 Sep, this revision
feat(matched)  dispatch on condition.retriever; delete KG_CONDITIONS; per-task token_budget
feat(matched)  budget generator + the two matched condition TOMLs
test(matched)  dispatch regression guard, the retriever map in the test fake, budget raise
exp(matched)   retrieval-side diagnostic table (no generation)
exp(matched)   matched runs, both legs (new run ids)
docs(matched)  WP12 note + regenerated WP9 cost tables + revision plan status
```

## Risks

| Risk | Fallback |
|---|---|
| Runs slip past 26 Sep | Step 1's diagnostic is a standalone deliverable and already answers the confound; ship it and describe the generation arm as future work. |
| The matched arms collapse to near-floor pass rates | That *is* the result: baseline ranking degrades sharply under a tight budget. Report it with the retention table as the mechanism. |
| A reviewer reads the ablation as an unfair baseline | Report both tables and name it an ablation, never a sixth condition. |
| The `retriever` keying change perturbs an existing condition | Six of the seven TOMLs set `retriever == condition_id`, so for them the change is a no-op by inspection. The seventh, `kg_augmented_hardened`, is the one to watch, and it has its own test. Gates: the no-diff regeneration of `wp5_outcomes.md`, and `wp8_anchor_robustness.py` still reproducing 626 / 1,532 / 772. *(restated 21 Sep)* |
| The keying change breaks a WP8 test and it is read as a KG regression | It is the test **fake** that goes stale, not the retriever: `conftest.py` sets `retriever=condition_id`, which is false for `kg_augmented_hardened`. Fix the fake first, in the same commit, so the failure never appears. *(added 21 Sep)* |

---

## Follow-on work *(added 21 Sep, after steps 0–7 landed)*

Executing this plan raised two questions its results cannot answer, and one of them qualifies the
headline: the all-or-nothing applier means "30 → 18" is an **upper bound on the damage**, not a
measurement. Planned separately as WP12 steps 8–9 —
[`wp12_anomalies_plan.md`](wp12_anomalies_plan.md) — because this file is a completed record and
those steps were discovered by executing it, not planned beside it. They also correct the
retention metric used above.

**Done 21 Sep.** Outcome: [`wp12_anomalies.md`](wp12_anomalies.md). Anomaly A cost one cell —
three of the four matched totals do not move under per-edit application, so they are
measurements rather than bounds. Anomaly B cost a claim — corrected retention is 8 of 12, not
11 of 12.

## Revisit WP8 after this lands *(added 21 Sep)*

WP12 changes code and tests that WP8 shipped and documented three days earlier, so WP8's artifacts
stop being self-consistent the moment WP12 lands. This is a **reminder, not a plan** — what to
re-check, not how. Do it after step 7 and before WP10's `results_summary.md` is finalised.

- **`wp8_anchor_extraction.md` §4 and §4.1** describe the dispatch and the silent-floor fix in terms
  of condition names and `KG_CONDITIONS`, which WP12 deletes. The finding stands; the prose stops
  matching the code.
- **WP8's orchestrator tests** (`tests/unit/generation/test_orchestrator.py:318-342`) and the
  `conftest.py` fake are rewritten by WP12 step 3, so the test inventory the WP8 note quotes is out
  of date.
- **Re-run `scripts/wp8_anchor_robustness.py`** and regenerate its table if anything moved. WP12's
  verification gate proves the *numbers* hold; this proves the committed *artifact* does.
- **Is `kg_augmented_hardened` now worth running?** WP12 builds the machinery for a second
  non-default arm and pays the wiring cost once. Whether the hardened KG arm should also get a run
  is an open question — deliberately not answered here, and not implied by anything above.

**Discharged 24 Sep** — [`wp8_anchor_extraction.md`](wp8_anchor_extraction.md) §8. All four items
re-checked: nothing in the WP8 note needed correcting (the first two items above over-predicted what
had gone stale), both generated WP8 artifacts regenerate byte-identically, and the hardened-arm
question is answered **against** running it, because on the logged anchors the hardened arm
reproduces `strict`'s context token for token.
