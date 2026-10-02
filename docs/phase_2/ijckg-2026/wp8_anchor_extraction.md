# WP8 — Anchor extraction: how anchors are found, what happens when they are wrong

> Written 21 Sep 2026, IJCKG 2026 revision. Answers reviewer R3's question on how anchor
> entities are extracted and how ambiguous or incorrect anchors are handled.
> Plan: [`wp8_anchor_extraction_plan.md`](wp8_anchor_extraction_plan.md).
> Generated evidence: [`wp8_anchor_measurement.md`](wp8_anchor_measurement.md) /
> [`.csv`](wp8_anchor_measurement.csv) (the classifier, replayed from the WP5 logs) and
> [`wp8_anchor_robustness.md`](wp8_anchor_robustness.md) /
> [`.json`](wp8_anchor_robustness.json) (the retriever, fed deliberately wrong anchors).
> Neither cost an API call.

**Terminology.** The component is the **classifier** (`src/retrieval/classifier.py`,
`call_purpose="classifier"`). Not "planner".

---

## 1. How an anchor is extracted and used

The KG-augmented retriever is template-heavy and agent-light. Exactly one LLM call per
candidate does any interpretation of the task statement:

1. **Classify.** `classify_task()` sends the raw task statement to the run's own model
   (never a third model — cross-model mixing is forbidden by D-LLM3) at temperature 0
   with `max_tokens=512`, and asks for JSON: a `task_type` of `bug_fix`,
   `feature_addition` or `refactoring`, a list of `anchor_names` (component or hook
   names), and a list of `anchor_routes` (URL paths).
2. **Dispatch.** `task_type` selects one of three Cypher templates. `anchor_names` and
   `anchor_routes` are bound as `$anchorNames` and `$anchorRoutes`.
3. **Scope.** Each of the three templates opens with

   ```cypher
   MATCH (:Project {projectId: $projectId})<-[:BELONGS_TO]-(f:File)<-[:DEFINED_IN]-(anchor)
   WHERE (anchor:Function_Component OR anchor:Class_Component OR anchor:Custom_Hook)
     AND anchor.name IN $anchorNames
   ```

   Matching is therefore **exact, case-sensitive equality against `name`**, scoped to the
   project. There is no similarity search, no embedding, no retry, and the anchor is the
   only thing that scopes the query: everything else in the context — props, hooks,
   state, parents, callers, delegated hook source — hangs off it.

Anchors are not a ranking signal that can be slightly wrong and still work. They are a
**hard filter**, and that is what makes their failure modes worth measuring.

---

## 2. What the classifier actually produced

Measured by replaying all **60** classifier calls the four WP5 KG runs logged (two
models × six tasks × n=5), scored against the reference patches and the committed graph
dumps. `scripts/wp8_anchor_report.py`; full tables in
[`wp8_anchor_measurement.md`](wp8_anchor_measurement.md).

| | Result |
|---|---|
| Task type | **60/60 correct**, both models, all six tasks. The malformed-response fallback never fired. |
| Distinct anchor names produced | 9 |
| Resolving to exactly one graph node | **8 of 9** |
| Ambiguous (one name, several nodes) | **0** — it did not occur in either repo |
| Calls extracting no anchor at all | **0** |
| Calls whose anchors all failed to resolve | **0** |

The single non-resolving anchor is `useCopyToClipboard` on P3 — the hook the task asks
the model to **create**. It is absent from the graph by construction, not an error, and
P3's other anchor (`NoteMenuBar`) resolved, so the query still returned its row.

**Anchor precision and recall against the reference patch** (an anchor is correct when it
names a component or hook defined in a file the patch edits, or the stem of a file the
patch creates):

| Task | Type | Precision | Recall | Note |
|---|---|---|---|---|
| P1 | bug_fix | 1.00 | 1.00 | |
| P2 | feature_addition | 1.00 | 1.00 | |
| P3 | refactoring | 1.00 | 1.00 | the created hook counts as truth |
| P4 | feature_addition | 1.00 | 0.67 | misses `useCartProducts`, two hops away — the pre-registered P4 expectation |
| P5 | refactoring | 0.71–0.77 | 1.00 | adds `useCart`, which the patch does not touch |
| P6 | bug_fix | 1.00 | 1.00 | |

### 2.1 `expected_anchors` was not usable ground truth

The task YAMLs carry an `expected_anchors` field. It disagreed with the classifier on
P1, P3, P4 and P5 — and on **P1 and P4 the classifier was right and the YAML was wrong**:
P1 named `CartProduct` where the reference patch edits `useCartProducts.ts`; P4 named
`Cart` alone where the statement says "add a `clearCart` function to the `useCart` hook".

`grep -rn expected_anchors --include=*.py` returns nothing: the field is **read by no
code**. It was documentation that had drifted. P1 and P4 are corrected in place with the
date and the reason, and the field is now marked documentation-only. Nothing re-ran, and
no measurement in this note depends on it — ground truth throughout is the reference
patch.

### 2.2 The classifier is not deterministic at temperature 0

Three of twelve (model × task) cells produced more than one distinct output:

- `useCart` appears as a P5 anchor in 3 of 5 Claude calls and 4 of 5 Qwen calls;
- Qwen emits `anchor_routes: ["/notes/trash"]` on 2 of 5 P2 calls.

This is provider-side variance — the same quantity WP5 reports as *distinct outputs* —
not sampling. It matters here because the anchor is a hard filter: the same task can
produce two different contexts on two runs.

### 2.3 A genuinely wrong anchor, in the wild

TakeNote's graph holds exactly two routes, `/` and `/app`. **`/notes/trash` does not
exist.** Qwen invented it on two P2 candidates and nothing flagged it at the time. This
is precisely the case R3 asked about, and it occurred without being noticed — which is
the honest answer to "how are incorrect anchors handled": before this work package, they
were not.

---

## 3. The latent defect, and five places that documented it backwards

Because `anchor.name IN $anchorNames` is **not** optional, an empty `$anchorNames` is
false for every node. The query returns **zero rows**, the assembler builds no target
components, and Format A renders its headers with nothing under them. **The
KG-augmented condition silently becomes the floor condition, which scored 0/30 in WP5.**
The same happens when every anchor is present but none of them matches a node.

Five statements across two files claimed the opposite — a project-wide fallback that was
never implemented:

| Where | What it claimed |
|---|---|
| `classifier.py`, `parse_classifier_response` docstring | "the templates then fall back to project-wide summaries" |
| `cypher_templates.md` §2 table | "templates handle this gracefully" |
| `cypher_templates.md` §2 prose | "fall back to returning project-wide structural summaries" |
| `cypher_templates.md` bug_fix §Fallback | "drop the `AND anchor.name IN $anchorNames` predicate" |
| `cypher_templates.md` L5 | "all three templates degrade to project-wide scans … will almost always blow the token budget" |

L5 had the risk exactly inverted: the failure is an *empty* context, not an oversized one.

**No WP5 candidate reached this path.** All 60 calls produced at least one resolving
anchor, so the defect is **latent, not realised, and the published results are
unaffected.** All five statements now describe what the code does.

---

## 4. Hardened resolution (implemented, opt-in, off by default)

`[retriever_params] anchor_resolution` on the condition:

- **`strict`** — the default, and what WP5 measured. Raw names, exact case-sensitive
  match. `conditions/base/kg_augmented.toml` is unchanged; the retriever takes the same
  code path and writes the same three metadata keys as before.
- **`hardened`** — `conditions/base/kg_augmented_hardened.toml`, a new condition that
  differs from `kg_augmented` in that one parameter and nothing else.

Under `hardened`, `anchor_candidates.cypher` returns every `Function_Component`,
`Class_Component` and `Custom_Hook` of the project (20 rows for react-shopping-cart, 48
for TakeNote — one cheap metadata scan), and `src/retrieval/anchor_resolver.py` resolves
each requested name against them:

| Rung | Rule |
|---|---|
| `exact` | `name` equality, as the templates do |
| `case_insensitive` | case-folded equality |
| `fuzzy` | `difflib` ratio ≥ 0.80 against the project's node names |
| `ambiguous` | any rung that ends with more than one candidate: every candidate is kept, ordered by the path segments it shares with a path the task statement names, and the alternatives are recorded alongside the choice |
| `unresolved` | nothing matched |

Exact runs before fuzzy for a specific reason: `CartProduct` and `CartProducts` are 0.957
similar, so a resolver that fuzzed first could rewrite one into the other. When both
names exist, the exact rung has already claimed the right one.

When **not one** anchor resolves, `project_overview.cypher` returns the project's largest
components by props + hooks + state — metadata only, no source, capped at 40 rows and
then by the same `token_budget` — with a warning note saying in the prompt itself that the
context is not task-scoped. This is the fallback the documentation had been promising,
now real and bounded. For a `feature_addition` the routing table is carried through as
well, since it is project-wide by construction.

**Nothing is silent.** Under `hardened` the retrieval metadata carries
`anchor_resolution`, the classifier's original `anchor_names`, the
`anchor_names_dispatched` that actually reached `$anchorNames`, one
`anchor_resolutions` record per requested name, `anchor_routes_unknown`, and an explicit
**`anchor_fallback`** flag. A candidate that degraded to project-wide context is visible
in the artifacts rather than inferred from a token count.

### 4.1 A defect found next door

The orchestrator's condition dispatch ended in `else: FloorRetriever(...)`. Any condition
whose TOML loaded but whose retriever branch was missing ran as floor and was recorded
under its own name — an entire arm of empty-context candidates with no trace of the
mistake. It now raises. Found while wiring the new condition; it would equally have hit
WP12.

---

## 5. Robustness: what happens when the anchor is wrong

`scripts/wp8_anchor_robustness.py`, retrieval only — no generator call, no harness, no
API; the classifier is replayed rather than called. P1–P3 cover all three task types.
Full table in [`wp8_anchor_robustness.md`](wp8_anchor_robustness.md).

| Anchor fed | `strict` (published) | `hardened` |
|---|---|---|
| The logged anchors | 1 row, **626 / 1532 / 772** tokens | identical |
| Misspelled (`useCartPorducts`, `NoteLsit`, `NoteMenuBra`) | **0 rows, 23–55 tokens** — headers only, silently | resolves by `difflib` (0.875–0.933) and **reproduces the logged context exactly** |
| Empty list | **0 rows, 23–55 tokens** — the latent defect | bounded overview, **198–594 tokens**, `anchor_fallback = true` |
| Wrong but real (`Checkbox`, `ContextMenu`, `CategoryList`) | 1 row, the wrong component's context | **the same** — resolves cleanly, not detected |
| Invented route `/notes/trash` | context carries the ⚠ note; nothing machine-readable | same context, plus `anchor_routes_unknown: ["/notes/trash"]` |

The misspelled and empty rows are the defect reproduced; the `hardened` column beside them
is the same defect fixed, in one table.

**Regression guard.** The `strict` + logged cells reproduce **626, 1532 and 772** context
tokens for P1, P2 and P3 — exactly the `context_tokens_median` values
`wp5_outcomes.csv` published for the KG condition. The script exits non-zero if they ever
stop matching, and no run directory under `harness_results/` or `candidate_artifacts/` was
touched by any of this work.

---

## 6. Known limits

1. **A wrong but real anchor cannot be detected.** `Checkbox` on P1 resolves to exactly
   one node, produces a well-formed 135-token context about the wrong component, and
   looks indistinguishable from success in the metadata. `/notes/trash` was caught only
   because TakeNote's graph holds two routes and the classifier's guess was outside them;
   a plausible-but-wrong *component* name has no such check. Detecting it would require
   grounding the anchor in the task's ground truth, which is exactly what the system is
   not allowed to see.
2. **Fuzzy matching can invent a resolution.** The resolver reports `status: fuzzy` and
   the ratio rather than hiding it, but a name 0.85 similar to a real component will be
   rewritten to it. The 0.80 cutoff is a stated choice, not a measured optimum — 9
   distinct anchors is far too small a sample to tune it on.
3. **The classifier is not deterministic**, so two runs of the same task can retrieve two
   different contexts (§2.2). This is a property of the providers at temperature 0, not
   of the retriever.
4. **The hardened path is measured on retrieval only.** It has not been run end-to-end
   through generation and the harness, so there is no pass-rate evidence for it, and
   none is claimed. It is off by default precisely so that it cannot affect the reported
   results.
5. **Only two repositories.** No name ambiguity occurred in either, so the ambiguity rung
   is exercised by unit tests and by the `Button` case `cypher_templates.md` L4 describes,
   not by real data.

---

## 7. What to say in the paper

- Anchor extraction is one LLM call producing a task type and a list of names; the names
  are a hard filter in the Cypher templates, not a ranking signal.
- On the pilot, task type was **60/60** and **8 of 9** distinct anchors resolved to
  exactly one node, with no ambiguity. The one miss is a file the task creates.
- The failure mode that matters is not ambiguity but **non-resolution**: because the
  anchor `MATCH` is non-optional, an unresolved anchor produces an empty context, so the
  KG condition degrades to the floor condition rather than to a weaker KG condition. This
  did not occur in the reported runs — it is a latent defect, now documented, reproduced
  and fixed behind an opt-in condition.
- The residual limit is stated plainly: a wrong but *real* anchor resolves cleanly and
  cannot be detected from the graph alone.

---

## 8. Re-checked against the post-WP12 code *(24 Sep)*

WP12 (21 Sep) rewrote the orchestrator's condition dispatch to key on the condition TOML's
`retriever` field and **deleted the `KG_CONDITIONS` name tuple this work package shipped
three days earlier**, so the reminder in
[`wp12_matched_context_plan.md`](wp12_matched_context_plan.md) asked for §4, §4.1, the
robustness table and WP8's tests to be re-checked before WP10 is finalised. Done on
24 Sep: **nothing in this note needed correcting.** The reminder over-predicted, and the
details are recorded here so the next reader does not repeat the check.

| What the reminder flagged | Verdict, 24 Sep |
|---|---|
| §4 / §4.1 "describe the dispatch in terms of condition names and `KG_CONDITIONS`" | **Not the case.** This note never names `KG_CONDITIONS`. §1's *Dispatch* step means `task_type` → Cypher template, which WP12 did not touch. |
| §4.1's silent-floor finding | **Still literally true.** The chain still ends in an `else`, which now raises; `src/generation/orchestrator.py` carries the reason in a comment crediting WP8/WP12, and `test_a_condition_with_no_retriever_raises_instead_of_running_as_floor` still guards it. |
| §4 "the same code path … the same three metadata keys as before" | **Verified.** `src/retrieval/kg_retriever.py` writes exactly `task_type`, `anchor_names` and `anchor_routes` under `strict`; the resolution keys are added only when the mode is not the default. |
| §4 "differs from `kg_augmented` in that one parameter and nothing else" | **Verified** against the two TOMLs. What routes the hardened arm to the KG retriever is now its own `retriever = "kg_augmented"` field rather than membership of a tuple — the *mechanism* changed, the sentence did not become false. |
| "the test inventory the WP8 note quotes is out of date" | **The note quotes no inventory.** §6.5's "exercised by unit tests" still holds (`tests/unit/retrieval/test_anchor_resolver.py`). WP12's rewrite kept both WP8 findings and added `PRE_WP12_DISPATCH` — a map of what each shipped condition dispatched to *before* WP12, which now fails if any published arm ever changes retriever without someone saying so. |
| "Re-run `scripts/wp8_anchor_robustness.py` … this proves the committed *artifact* does" | **Regenerates byte-identically**, 626 / 1532 / 772 regression guard included. [`wp8_anchor_measurement.md`](wp8_anchor_measurement.md) too. `_dispatch`'s signature — the plan's own acceptance criterion — is unchanged since its original commit. |

Unit suite: **736 passed.**

### 8.1 The open question: should `kg_augmented_hardened` be run end to end?

WP12 built the machinery for a second non-default arm and paid the wiring cost once, which
is what made this worth asking. **The evidence in §5 argues against running it.** On the
*logged* anchors — all 60 of which resolved — the hardened arm reproduces `strict`'s context
**exactly, token for token, on all three tasks**. An end-to-end hardened run can therefore
differ from `kg_augmented` only on a candidate whose anchor fails to resolve, and no WP5
candidate did. What such a run would actually measure is classifier nondeterminism (§2.2) at
n = 5, not hardening — a lottery rather than a comparison. §6.4's position, that the hardened
path is measured on retrieval only and no pass-rate evidence is claimed, is both cheaper and
easier to defend.

Cost if it is run anyway, for the record: 60 candidates (6 tasks × 5 × 2 legs), about
**$0.7** at the WP9 per-candidate KG figures and roughly **two hours** of wall clock at the
calibrated timeouts. Nothing else in the revision depends on the answer.
