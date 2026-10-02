# WP6 annotation — jira_clone · `src/shared/components/PageLoader/index.jsx`

<!-- wp6 v1 project=jira_clone path=src/shared/components/PageLoader/index.jsx sha=26a9e77b1789fef9cb43edb5d6018cf1663cf035 graph=graph_export/jira_clone/full_dump.cypherl prompt_set=72ef9f041851 -->

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
 1  import React from 'react';
 2  
 3  import Spinner from 'shared/components/Spinner';
 4  
 5  import StyledPageLoader from './Styles';
 6  
 7  const PageLoader = () => (
 8    <StyledPageLoader>
 9      <Spinner size={70} />
10    </StyledPageLoader>
11  );
12  
13  export default PageLoader;
````

## Step 2 — Review what the extractor found

Set every `[ ]` to `[y]` (correct), `[n]` (wrong) or `[?]` (unsure). An item that is
right but points at the wrong target is `[n]`; add the right one in step 3. Add
` # cause: resolution|llm|schema` or any note after an item if useful.

<!-- wp6:items -->

### LLM-extracted nodes (1)

- [y] N Function_Component:PageLoader

### LLM-extracted edges (3)

- [y] E DEFINED_IN Function_Component:PageLoader -> File
- [y] E PASSES_PROP Function_Component:PageLoader -> Function_Component:Spinner@src/shared/components/Spinner.jsx prop=size
- [y] E USES_COMPONENT Function_Component:PageLoader -> Function_Component:Spinner@src/shared/components/Spinner.jsx

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
