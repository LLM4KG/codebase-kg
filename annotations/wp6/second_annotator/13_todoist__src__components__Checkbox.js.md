# WP6 annotation — todoist · `src/components/Checkbox.js`

<!-- wp6 v1 project=todoist path=src/components/Checkbox.js sha=f998b9af73a1d533e52a9a3f5545216904faf077 graph=graph_export/todoist/full_dump.cypherl prompt_set=72ef9f041851 -->

status: done
annotator: annotator_2

> Guide: `docs/phase_2/ijckg-2026/annotation_guide.md`. Work top to bottom and **finish
> step 1 before you read step 2**. Set `status:` to `done` when the file is finished.

## Step 1 — Read the source, then note what you see (not scored)

List the components, hooks, props, state, handlers, contexts and routes you find, and
what each component renders and uses. Do this *before* looking at step 2.

<!-- wp6:notes -->

<!-- wp6:notes-end -->

Source at `f998b9a`:

````js
 1  import React from 'react';
 2  import PropTypes from 'prop-types';
 3  import { firebase } from '../firebase';
 4  
 5  export const Checkbox = ({ id, taskDesc }) => {
 6    const archiveTask = () => {
 7      firebase.firestore().collection('tasks').doc(id).update({
 8        archived: true,
 9      });
10    };
11  
12    return (
13      <div
14        className="checkbox-holder"
15        data-testid="checkbox-action"
16        onClick={() => archiveTask()}
17        onKeyDown={(e) => {
18          if (e.key === 'Enter') archiveTask();
19        }}
20        aria-label={`Mark ${taskDesc} as done?`}
21        role="button"
22        tabIndex={0}
23      >
24        <span className="checkbox" />
25      </div>
26    );
27  };
28  
29  Checkbox.propTypes = {
30    id: PropTypes.string.isRequired,
31    taskDesc: PropTypes.string.isRequired,
32  };
````

## Step 2 — Review what the extractor found

Set every `[ ]` to `[y]` (correct), `[n]` (wrong) or `[?]` (unsure). An item that is
right but points at the wrong target is `[n]`; add the right one in step 3. Add
` # cause: resolution|llm|schema` or any note after an item if useful.

<!-- wp6:items -->

### LLM-extracted nodes (5)

- [y] N Function_Component:Checkbox
- [y] N Prop:Checkbox::id
- [y] N Prop:Checkbox::taskDesc
- [y] N EventHandler:Checkbox::inline_onClick
- [y] N EventHandler:Checkbox::inline_onKeyDown

### LLM-extracted edges (5)

- [y] E ACCEPTS_PROP Function_Component:Checkbox -> Prop:Checkbox::id
- [y] E ACCEPTS_PROP Function_Component:Checkbox -> Prop:Checkbox::taskDesc
- [y] E DEFINED_IN Function_Component:Checkbox -> File
- [y] E HAS_HANDLER Function_Component:Checkbox -> EventHandler:Checkbox::inline_onClick
- [y] E HAS_HANDLER Function_Component:Checkbox -> EventHandler:Checkbox::inline_onKeyDown

### Deterministic (sanity scope) (2)

- [y] N File
- [y] E BELONGS_TO File -> Project:todoist

<!-- wp6:items-end -->

## Step 3 — What the extractor missed

One item per line, in the step-2 syntax, without the checkbox. `@path` defaults to this
file. Examples:

    N Prop:Button::onClick
    E USES_COMPONENT Function_Component:App -> Function_Component:Header@src/Header.tsx

<!-- wp6:missed -->

<!-- wp6:missed-end -->
