# WP6 annotation — SnapShot · `src/components/Navigation.js`

<!-- wp6 v1 project=SnapShot path=src/components/Navigation.js sha=d6ea1fd3fd74f6bbfa8794963b6743ac5be61757 graph=graph_export/SnapShot/full_dump.cypherl prompt_set=72ef9f041851 -->

status: done
annotator: annotator_1

> Guide: `docs/phase_2/ijckg-2026/annotation_guide.md`. Work top to bottom and **finish
> step 1 before you read step 2**. Set `status:` to `done` when the file is finished.

## Step 1 — Read the source, then note what you see (not scored)

List the components, hooks, props, state, handlers, contexts and routes you find, and
what each component renders and uses. Do this *before* looking at step 2.

<!-- wp6:notes -->

<!-- wp6:notes-end -->

Source at `d6ea1fd`:

````js
 1  import React from 'react';
 2  import { NavLink } from 'react-router-dom';
 3  
 4  const Navigation = () => {
 5    return (
 6      <nav className="main-nav">
 7        <ul>
 8          <li><NavLink to="/mountain">Mountain</NavLink></li>
 9          <li><NavLink to="/beach">Beaches</NavLink></li>
10          <li><NavLink to="/bird">Birds</NavLink></li>
11          <li><NavLink to="/food">Food</NavLink></li>
12        </ul>
13      </nav>
14    );
15  }
16  
17  export default Navigation;
````

## Step 2 — Review what the extractor found

Set every `[ ]` to `[y]` (correct), `[n]` (wrong) or `[?]` (unsure). An item that is
right but points at the wrong target is `[n]`; add the right one in step 3. Add
` # cause: resolution|llm|schema` or any note after an item if useful.

<!-- wp6:items -->

### LLM-extracted nodes (1)

- [y] N Function_Component:Navigation

### LLM-extracted edges (1)

- [y] E DEFINED_IN Function_Component:Navigation -> File

### Deterministic (sanity scope) (2)

- [y] N File
- [y] E BELONGS_TO File -> Project:snapshot

<!-- wp6:items-end -->

## Step 3 — What the extractor missed

One item per line, in the step-2 syntax, without the checkbox. `@path` defaults to this
file. Examples:

    N Prop:Button::onClick
    E USES_COMPONENT Function_Component:App -> Function_Component:Header@src/Header.tsx

<!-- wp6:missed -->

<!-- wp6:missed-end -->
