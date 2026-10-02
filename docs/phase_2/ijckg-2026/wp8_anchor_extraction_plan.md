# WP8 — Anchor extraction (check, harden, report): implementation plan

> Written 21 Sep 2026. Referenced from the WP8 section of
> [`revision_implementation_plan_18-22Sep.md`](revision_implementation_plan_18-22Sep.md).
> The §2 measurement was carried out while writing this plan, from the committed logs, with no API
> spend; the numbers below are measured, not projected.

## Context

R3 asked how anchor entities are extracted and how ambiguous or incorrect anchors are handled.
The WP8 stub schedules a behaviour check (§1), a measurement (§2), optional hardening (§3) and a
note. Doing the measurement first changed what the work should be: **the classifier is in better
shape than assumed, and the unresolved-anchor path is in worse shape and documented backwards.**

Deliverable: `docs/phase_2/ijckg-2026/wp8_anchor_extraction.md`, with the hardening behind a new
opt-in condition so that no published result moves.

## What the measurement found

60 classifier calls — both legs × P1–P6 × n=5, from
`{claude_primary,qwen_robustness}_2026-09-{18_wp5_p1p3,19_wp5_p4p6}`.

- **Task type: 60/60 correct**, both models, every task. The malformed-response fallback never
  fired.
- **Anchor resolution: 9 of 10 distinct anchors resolve to exactly one graph node.** No ambiguity
  occurred in either repo. The single miss is `useCopyToClipboard` (P3) — the file the task
  *creates*, so unresolvable by construction rather than wrong.
- **The classifier beats its own stated ground truth.** `expected_anchors` in the task YAMLs
  disagrees on P1, P3, P4 and P5, and on P1 and P4 the classifier is right against the reference
  patch:

  | Task | `expected_anchors` | Classifier | Reference patch | Verdict |
  |---|---|---|---|---|
  | P1 | `CartProduct` | `useCartProducts` | `useCartProducts.ts` | YAML wrong |
  | P2 | `NoteList` | `NoteList` | `NoteList.tsx`, `note.ts`, `TestID.ts` | match |
  | P3 | `NoteMenuBar` | `NoteMenuBar`, `useCopyToClipboard` | `NoteMenuBar.tsx`, creates `useCopyToClipboard.ts` | extra anchor is the file being created |
  | P4 | `Cart` | `useCart`, `Cart` | `Cart.tsx`, `useCart.ts`, `useCartProducts.ts` | YAML incomplete |
  | P5 | `CartProduct`, `CartProducts` | + `useCart` (3–4 of 5) | `CartProduct.tsx`, `CartProducts.tsx` | extra |
  | P6 | `CategoryList` | `CategoryList` | `CategoryList.tsx` | match |

  `expected_anchors` is **read by no code** — `grep -rn expected_anchors --include=*.py` returns
  nothing. It is documentation only.
- **Not deterministic at temperature 0.** Three of twelve cells vary: `useCart` appears in 3/5
  (Claude P5) and 4/5 (Qwen P5); Qwen P2 emits `anchor_routes: ["/notes/trash"]` on 2 of 5 runs.
  This is provider-side variance, the same phenomenon WP5 reports as "distinct outputs".
- **A genuinely wrong anchor, in the wild.** TakeNote's graph contains exactly two routes, `/` and
  `/app`. `/notes/trash` does not exist. Qwen hallucinated it on two P2 candidates and nothing
  noticed — which is exactly the case R3 asked about.

## The latent bug §1 was meant to find

All three anchor-scoped templates — `bug_fix.cypher:18-20`, `feature_addition_a.cypher:7-9`,
`refactoring.cypher:13-15` — open with a **non-optional**
`MATCH … WHERE anchor.name IN $anchorNames`. With an empty list that predicate is false for every
node, so the query returns **zero rows**, the assembler builds no target components, and Format A
renders headers only. **The KG-augmented condition silently becomes the floor condition, which
scored 0/30.** Only `feature_addition_b` (routing) is genuinely project-wide.

Five statements across two files claim the opposite, describing a fallback that was never
implemented:

| Where | Claim |
|---|---|
| `src/retrieval/classifier.py`, `parse_classifier_response` docstring | "the templates then fall back to project-wide summaries" |
| `src/retrieval/templates/cypher_templates.md:30` | "templates handle this gracefully" |
| `cypher_templates.md:33` | "fall back to returning project-wide structural summaries" |
| `cypher_templates.md:141` | "drop the `AND anchor.name IN $anchorNames` predicate" |
| `cypher_templates.md:464-465` (L5) | "all three templates degrade to project-wide scans … will almost always blow the token budget" |

No WP5 candidate hit this path — every anchor resolved — so the bug is **latent, not realised**, and
the note should say so plainly rather than implying the published results are affected.

---

## Design decisions

- **Hardening is opt-in, so nothing published moves.** `[retriever_params] anchor_resolution` on the
  condition, defaulting to `"strict"` (today's exact-name match).
  `conditions/base/kg_augmented.toml` keeps the default, so the WP5 replay and
  `scripts/wp9_retrieval_timing.py` stay byte-identical. A new
  `conditions/base/kg_augmented_hardened.toml` sets `"hardened"`. Same pattern as WP12.
- **Ground truth is the reference patch**, as the WP8 stub's §2 already says — not
  `expected_anchors`. An anchor is correct when it names a component or hook defined in a file the
  patch edits, or a file the patch creates.
- **The stale `expected_anchors` are corrected** (P1, P4) with a comment giving the date and the
  reason. Safe: the field is documentation-only, so nothing re-runs.
- **Never silently empty.** Whatever the hardening does, `retrieval_metadata` must carry each
  anchor's resolution status and an explicit `anchor_fallback` flag. A KG candidate that degraded to
  floor-equivalent context must be visible in the artifacts, not inferred from a token count.
- **No WP5 re-runs.** Per the WP8 stub's §4, hardening is a new retriever version.

---

## Steps

**0. Record the plan.** This file, linked from the revision plan. Commit alone — `docs(anchor)`.

**1. Measurement script.** `scripts/wp8_anchor_report.py`, deterministic and re-runnable:
- read classifier records from the four WP5 run logs, map each to its task with `match_task`
  (`src/evaluation/cost.py:69`) and re-parse with `parse_classifier_response` — the same replay
  approach as `scripts/wp9_retrieval_timing.py:80`;
- derive ground truth from `tasks/pilot/patches/`;
- resolve every anchor against `graph_export/*/full_dump.cypherl` by parsing the dump, so no
  Memgraph is needed;
- emit task-type accuracy, anchor precision/recall per task and model, per-anchor resolution status,
  distinct outputs per cell, and the hallucinated-route finding;
- write `docs/phase_2/ijckg-2026/wp8_anchor_extraction.{md,csv}`.

**2. Correct the stale ground truth** in `tasks/pilot/P1*.yaml` and `P4*.yaml`
(`CartProduct` → `useCartProducts`; `Cart` → `Cart`, `useCart`), each with a comment recording the
correction, its date and that the field is documentation-only. P3's `useCopyToClipboard` and P5's
`useCart` are explained in the note, not changed in the YAML.

**3. Fix the five false statements** in `classifier.py` and `cypher_templates.md` so they describe
zero rows and a near-empty context. Worth doing even on its own: documentation that contradicts the
code is worse than silence.

**4. Anchor resolver** — new `src/retrieval/anchor_resolver.py`:
- one new template `src/retrieval/templates/anchor_candidates.cypher` returning
  `(name, uid, filePath, label)` for every `Function_Component` / `Class_Component` / `Custom_Hook`
  in the project (44 rows for TakeNote — cheap);
- `resolve_anchors(names, rows, spec) -> list[AnchorResolution]` with
  `status ∈ {exact, case_insensitive, fuzzy, ambiguous, unresolved}`; fuzzy via stdlib
  `difflib.get_close_matches` at a stated cutoff;
- ambiguity: keep every candidate but order by path segments shared with any path named in the
  spec, recording both the choice and the alternatives — the `Button` case already described at
  `cypher_templates.md:462`;
- a pure function over rows, so it unit-tests without a database.

**5. Wire it in** (`src/retrieval/kg_retriever.py`):
- under `"hardened"`, resolve before `_dispatch`, pass the resolved node names, and record every
  `AnchorResolution` plus `anchor_fallback` in the result metadata;
- when nothing resolves, run a **bounded** project overview
  (`src/retrieval/templates/project_overview.cypher`: top components by props + hooks + state,
  truncated by the existing `token_budget`) and log a warning — the fallback the documentation has
  been claiming all along, now real and budget-capped;
- under `"strict"` the code path is exactly today's. **`_dispatch`'s signature must not change**, or
  `scripts/wp9_retrieval_timing.py` breaks.

**6. Robustness check** — `scripts/wp8_anchor_robustness.py`, retrieval-only: no generation, no
harness, no API. On P1–P3 feed (a) the logged anchors, (b) a misspelling (`CartProdcut`), (c) a
wrong-but-real component name, (d) an empty list, (e) the hallucinated `/notes/trash` route, and
record resolution status, rows returned and context tokens under both `strict` and `hardened`. This
is the table that answers R3 directly. Needs the scratch Memgraph on `bolt://localhost:7688`, with
the same guard `wp9_retrieval_timing.py` uses.

**7. Tests** (`tests/unit/retrieval/test_anchor_resolver.py`, `…/test_kg_retriever.py`): each
resolution status resolves as labelled; ambiguity prefers the spec-named path; `strict` leaves
behaviour and metadata unchanged (regression guard); `hardened` with no resolvable anchor produces a
non-empty bounded context and sets `anchor_fallback`.

**8. Note + fold into WP10.** `wp8_anchor_extraction.md` covers current behaviour, the measurement,
the resolver design, the robustness table, and the known limit the stub already names: **a wrong but
real anchor cannot be detected.** `/notes/trash` was caught only because the graph holds two routes;
a plausible-but-wrong *component* name would resolve cleanly and mislead quietly.

---

## Verification

- `uv run pytest tests/unit -q` green, including the `strict` regression guard.
- `scripts/wp8_anchor_report.py` run twice writes identical files — the same determinism WP7
  requires of its scorer.
- `conditions/base/kg_augmented.toml` unchanged, and a KG retrieve under it gives the same
  `retrieval_token_count` as the WP5 artifacts for that task — spot-check P2 at 1,532.
- `scripts/wp9_retrieval_timing.py` still imports and replays against `_dispatch` unchanged.
- `git status` shows no modification under any `harness_results/` or `candidate_artifacts/` run
  directory.
- The robustness run shows the empty-anchor case producing a bounded non-empty context under
  `hardened` and the near-empty context under `strict` — the bug reproduced and fixed in one table.

## Commits

```
docs(anchor)  WP8 plan
docs(anchor)  correct the five false empty-anchor claims; correct P1/P4 expected_anchors
exp(anchor)   classifier measurement script + wp8_anchor_extraction.{md,csv}
feat(anchor)  anchor_resolver + anchor_candidates/project_overview templates
feat(anchor)  opt-in hardened resolution + resolution metadata; kg_augmented_hardened.toml
test(anchor)  resolver cases, strict regression guard, fallback is non-empty
exp(anchor)   robustness table (misspelled / wrong / empty / hallucinated-route anchors)
docs(anchor)  WP8 note + revision plan status
```

## Risks

| Risk | Fallback |
|---|---|
| Steps 4–6 slip | Steps 1–3 stand alone: the measurement and the documentation fix are the part that answers R3, and the WP8 stub already allows shipping §1–2 with §3 as design. |
| The hardened path perturbs the published KG condition | It is opt-in and off by default; the regression guard and the P2 token spot-check are the gates. |
| Fuzzy matching invents a resolution for a genuinely wrong anchor | Report the status rather than hide it, and state the known limit that a plausible-but-wrong component name resolves cleanly and cannot be detected. |
| `_dispatch` changes break `wp9_retrieval_timing.py` | Its signature is fixed; resolution happens before the call, and the timing script is re-run as a check. |
