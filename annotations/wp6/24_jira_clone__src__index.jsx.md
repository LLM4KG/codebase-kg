# WP6 annotation — jira_clone · `src/index.jsx`

<!-- wp6 v1 project=jira_clone path=src/index.jsx sha=26a9e77b1789fef9cb43edb5d6018cf1663cf035 graph=graph_export/jira_clone/full_dump.cypherl prompt_set=72ef9f041851 -->

status: done
annotator: annotator_1

> Guide: `docs/phase_2/ijckg-2026/annotation_guide.md`. Work top to bottom and **finish
> step 1 before you read step 2**. Set `status:` to `done` when the file is finished.

## Step 1 — Read the source, then note what you see (not scored)

List the components, hooks, props, state, handlers, contexts and routes you find, and
what each component renders and uses. Do this *before* looking at step 2.

<!-- wp6:notes -->

<!-- wp6:notes-end -->

Source at `26a9e77`:

````jsx
 1  import 'core-js/stable';
 2  import 'regenerator-runtime/runtime';
 3  
 4  import React from 'react';
 5  import ReactDOM from 'react-dom';
 6  
 7  import App from 'App';
 8  
 9  ReactDOM.render(<App />, document.getElementById('root'));
````

## Step 2 — Review what the extractor found

Set every `[ ]` to `[y]` (correct), `[n]` (wrong) or `[?]` (unsure). An item that is
right but points at the wrong target is `[n]`; add the right one in step 3. Add
` # cause: resolution|llm|schema` or any note after an item if useful.

<!-- wp6:items -->

### LLM-extracted nodes (0)

(none)

### LLM-extracted edges (1)

- [y] E RENDERS_ROOT_COMPONENT File -> Function_Component:App@src/App/index.jsx

### Deterministic (sanity scope) (2)

- [y] N File
- [y] E BELONGS_TO File -> Project:jira_client

<!-- wp6:items-end -->

## Step 3 — What the extractor missed

One item per line, in the step-2 syntax, without the checkbox. `@path` defaults to this
file. Examples:

    N Prop:Button::onClick
    E USES_COMPONENT Function_Component:App -> Function_Component:Header@src/Header.tsx

<!-- wp6:missed -->

<!-- wp6:missed-end -->
