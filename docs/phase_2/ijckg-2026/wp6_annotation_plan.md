# WP6 — Ground-truth annotation set-up: plan

> Written 19 Sep 2026. Parent: WP6 in
> [`revision_implementation_plan_18-22Sep.md`](revision_implementation_plan_18-22Sep.md).
> Consumer: WP7 (scoring). Deliverables for Anjana by the end of 20 Sep: the annotation guide,
> the sample list and the pre-filled annotation files.

## Facts this design rests on (checked 19 Sep)

- **Five graphs of record**, all committed under `graph_export/<project>/`. Each was extracted by
  `anthropic/claude-sonnet-4-6` with prompt set `72ef9f041851`. The checkouts in
  `~/Study/Implementation/sample-projects` are clean and at each graph's recorded SHA.

  | Project | Checkout | SHA | Files |
  |---|---|---|---|
  | react-shopping-cart | `small/react-shopping-cart` | `9fa5624` | 55 |
  | SnapShot | `small/SnapShot` | `d6ea1fd` | 15 |
  | Todoist | `small/todoist` | `f998b9a` | 19 |
  | TakeNote | `medium/takenote` | `e0eddbb` | 60 |
  | Jira Clone | `medium/jira_clone/client` | `26a9e77` | 134 |

- **Types present.**
  - All 11 node types occur. `Class_Component` occurs once, in SnapShot.
  - 18 of the 30 relationship types occur. `IMPORTS` is **never created**: no pipeline query
    produces it, so it is an unimplemented type, not an extraction miss.
  - `DECLARES_CLASS_STATE` is implemented, but no repo has class state.
- **Multi-edges.** `PASSES_PROP` repeats between the same pair of components, once per prop, and
  is told apart by `propName`. `ROUTES_TO` carries `path`.

## Decisions

1. **Where an edge is annotated: in its evidence file, not "either endpoint".** The revision plan
   says a cross-file edge counts when either endpoint is in a sampled file. But an annotator can
   judge an edge, or notice that one is missing, only from the file whose code states it. That file
   is the **source** endpoint's file (`App` renders `Cart` → `App.tsx`; `Cart` accepts `products`
   → `Cart.tsx`), or the file itself for `File`-sourced edges (`RENDERS_ROOT_COMPONENT`).
   - Incoming edges, such as a parent in another file using this file's component, would force a
     search of the whole repo for callers. Recall could not be measured for them.
   - Every edge still has exactly one evidence file, so the WP7 counts remain a sample of all
     edges.
   - Cross-file targets are judged from the file's imports.
2. **Identity.** Node identity is type + name + file (the plan's rule). `Prop`, `State_Variable`
   and `EventHandler` also carry their owning component, as their `uid` does; otherwise
   two components in one file with a prop of the same name would collide. `Library_Hook` identity
   is name + source (`useState@react`).

   Edge identity is type + both endpoints, plus `propName` for `PASSES_PROP` and `path` for
   `ROUTES_TO`. These values distinguish multi-edges, so they are part of the identity, not
   attributes. All other attributes are out of scope.
3. **Scopes** (as the plan requires): the headline is the **LLM scope**. The **deterministic
   scope** is `Project`, `File`, `Library`, `BELONGS_TO`, `DEPENDS_ON`, `PROVIDED_BY`.
   - `File`, `BELONGS_TO` and the `PROVIDED_BY` edges of hooks the file uses are annotated per
     file, in their own section.
   - `Project`, `Library` and `DEPENDS_ON` are package-level. WP7 checks them **programmatically**
     against `package.json` at the pinned SHA; nobody annotates 98 `Library` rows by hand.
   - `DEFINED_IN`, `RENDERS_ROOT_COMPONENT` and `USES_CUSTOM_HOOK` are programmatic too, but each
     is derived from LLM output, so they stay in the LLM scope. WP7 can report them separately.
   - `Library_Hook` nodes are global and are scored through their edges.
   - `IMPORTS` is excluded and reported as "not implemented".
4. **Sampling** (`scripts/wp6_build_annotation_set.py`, seed `20260920`, deterministic).
   - **Quotas, 28 files:** react-shopping-cart 6, SnapShot 5, Todoist 5, TakeNote 6, Jira Clone 6.
   - **Pass 1, coverage.** Take in-scope types in order of rarity. For each type the sample does
     not cover yet, pick a seeded-random file that contains it (as evidence file) from a repo with
     quota left.
   - **Pass 2, stratified fill.** Each repo gets one file drawn from its files with **no
     LLM-extracted items**, which keeps completely missed files measurable. The rest of its quota
     is filled uniformly from its other files. The two strata are reported separately in WP7.
     - *Changed from uniform on 19 Sep, after measuring.* 105 of the 283 files have no LLM items:
       barrels, `style.ts` files and utilities (react-shopping-cart 33 of 55, Jira Clone 50 of 134).
     - A uniform fill put 11 of 28 sampled files there, including 4 of react-shopping-cart's 6.
       That left 96 nodes and 194 edges to score.
     - With one such file per repo, the other slots go to files with extracted content.
     - Recall on the no-item stratum is under-sampled relative to its share of files. WP7 states
       this.
   - **Known bias:** pass 1 covers the types the *extractor* found. A type it missed everywhere
     cannot steer the sample. Stated in the WP7 notes.
   - **Order: repo by repo, smallest first** (react-shopping-cart, SnapShot, Todoist, TakeNote,
     Jira Clone), then by path, so annotation that runs out of time leaves whole repos complete.
   - Saved to `annotations/wp6/sample.json`, with each file's sampling reason ("covers X" or
     "fill") and the seed.
5. **Second annotator:** a seeded subset of 4 files, one from each of the first four repos, copied
   to `annotations/wp6/second_annotator/`. They're used only if someone is available.
6. **Annotation file** (`annotations/wp6/<nn>_<project>__<path-slug>.md`, one per sampled file,
   plain text so it diffs):
   - a header with project, path, SHA, graph and prompt set, plus `status: todo`;
   - **Step 1, blind:** the full source with line numbers, and a free-notes box. The annotator
     lists what they see *before* reading step 2. This is the bias mitigation the plan asks for.
     The notes are not scored.
   - **Step 2:** the extractor's items, pre-filled. Each is `- [ ]`, to be set to `[y]` (correct)
     or `[n]` (wrong), or `[?]` if unsure. **Nothing is pre-ticked.** Every item needs an explicit
     decision, and an undecided item is reported as incomplete rather than silently accepted.
     Items come in three sections: LLM nodes, LLM edges, deterministic.
   - **Step 3:** missed items, one per line, in the same syntax.
   - An optional `# cause: resolution|llm|schema` note on any line, for WP7's error attribution.
     Stage 4 resolution is a separate error source (WP1 note).
7. **One line syntax for pre-filled and missed items**, parsed by `src/evaluation/annotation.py`:

   ```
   N Function_Component:CategoryList
   N Prop:Button::onClick                      (owned types: Owner::name, the uid's separator;
                                                both parts can contain dots)
   E USES_COMPONENT Function_Component:CategoryList -> Function_Component:AddCategoryForm@src/client/components/AppSidebar/AddCategoryForm.tsx
   E PASSES_PROP Function_Component:CategoryList -> Function_Component:AddCategoryForm@src/.../AddCategoryForm.tsx prop=submitHandler
   E USES_LIBRARY_HOOK Function_Component:CategoryList -> Library_Hook:useState@react
   ```

   `@path` defaults to this file.
   - **Round-trip test:** parsing a freshly pre-filled file gives back exactly the KG's items for
     that file. That makes the pre-fill checkable, and WP7 can reuse the parser.
   - The parser also reports undecided and malformed lines, so a half-annotated file shows up as
     incomplete.

## Files

- **New** `src/evaluation/__init__.py`, `src/evaluation/kg_dump.py`: reads a `.cypherl` dump into
  nodes and edges, with no Memgraph needed.
- **New** `src/evaluation/annotation.py`: item identities, evidence-file assignment, rendering, and
  a parser for the annotation files.
- **New** `scripts/wp6_build_annotation_set.py`: sampling, pre-fill, sample list and the second
  annotator's copies. Refuses to overwrite an annotation file whose status is not `todo`.
- **New** `tests/unit/evaluation/`: dump parsing, identities, render→parse round trip, verdict and
  missed-item parsing, sampling determinism and coverage.
- **New** `docs/phase_2/ijckg-2026/annotation_guide.md`: the protocol, per-type rules with one
  positive and one negative example each, matching rules, scopes, syntax and edge cases.
- **New** `annotations/wp6/`: the sample list and the 28 pre-filled files (+ 4 copies).

## Verification

- `uv run pytest tests/unit -q` green.
- Build the set twice: byte-identical output (seeded).
- Every in-scope type the five graphs contain appears in at least one sampled file, and the
  script prints the coverage table.
- Every pre-filled file parses back to the KG's items for that file.
