# WP6 annotation — todoist · `src/components/Projects.js`

<!-- wp6 v1 project=todoist path=src/components/Projects.js sha=f998b9af73a1d533e52a9a3f5545216904faf077 graph=graph_export/todoist/full_dump.cypherl prompt_set=72ef9f041851 -->

status: done
annotator: annotator_1

> Guide: `docs/phase_2/ijckg-2026/annotation_guide.md`. Work top to bottom and **finish
> step 1 before you read step 2**. Set `status:` to `done` when the file is finished.

## Step 1 — Read the source, then note what you see (not scored)

List the components, hooks, props, state, handlers, contexts and routes you find, and
what each component renders and uses. Do this *before* looking at step 2.

<!-- wp6:notes -->

<!-- wp6:notes-end -->

Source at `f998b9a`:

````js
 1  import React, { useState } from 'react';
 2  import PropTypes from 'prop-types';
 3  import { useSelectedProjectValue, useProjectsValue } from '../context';
 4  import { IndividualProject } from './IndividualProject';
 5  
 6  export const Projects = ({ activeValue = null }) => {
 7    const [active, setActive] = useState(activeValue);
 8    const { setSelectedProject } = useSelectedProjectValue();
 9    const { projects } = useProjectsValue();
10  
11    return (
12      projects &&
13      projects.map((project) => (
14        <li
15          key={project.projectId}
16          data-testid="project-action-parent"
17          data-doc-id={project.docId}
18          className={
19            active === project.projectId
20              ? 'active sidebar__project'
21              : 'sidebar__project'
22          }
23        >
24          <div
25            role="button"
26            data-testid="project-action"
27            tabIndex={0}
28            aria-label={`Select ${project.name} as the task project`}
29            onClick={() => {
30              setActive(project.projectId);
31              setSelectedProject(project.projectId);
32            }}
33            onKeyDown={(e) => {
34              if (e.key === 'Enter') {
35                setActive(project.projectId);
36                setSelectedProject(project.projectId);
37              }
38            }}
39          >
40            <IndividualProject project={project} />
41          </div>
42        </li>
43      ))
44    );
45  };
46  
47  Projects.propTypes = {
48    activeValue: PropTypes.bool,
49  };
````

## Step 2 — Review what the extractor found

Set every `[ ]` to `[y]` (correct), `[n]` (wrong) or `[?]` (unsure). An item that is
right but points at the wrong target is `[n]`; add the right one in step 3. Add
` # cause: resolution|llm|schema` or any note after an item if useful.

<!-- wp6:items -->

### LLM-extracted nodes (5)

- [y] N Function_Component:Projects
- [y] N Prop:Projects::activeValue
- [y] N State_Variable:Projects::active
- [y] N EventHandler:Projects::inline_onClick
- [y] N EventHandler:Projects::inline_onKeyDown

### LLM-extracted edges (8)

- [y] E ACCEPTS_PROP Function_Component:Projects -> Prop:Projects::activeValue
- [y] E DECLARES_STATE Function_Component:Projects -> State_Variable:Projects::active
- [y] E DEFINED_IN Function_Component:Projects -> File
- [y] E HAS_HANDLER Function_Component:Projects -> EventHandler:Projects::inline_onClick
- [y] E HAS_HANDLER Function_Component:Projects -> EventHandler:Projects::inline_onKeyDown
- [y] E PASSES_PROP Function_Component:Projects -> Function_Component:IndividualProject@src/components/IndividualProject.js prop=project
- [y] E USES_COMPONENT Function_Component:Projects -> Function_Component:IndividualProject@src/components/IndividualProject.js
- [y] E USES_LIBRARY_HOOK Function_Component:Projects -> Library_Hook:useState@react

### Deterministic (sanity scope) (3)

- [y] N File
- [y] E BELONGS_TO File -> Project:todoist
- [y] E PROVIDED_BY Library_Hook:useState@react -> Library:react

<!-- wp6:items-end -->

## Step 3 — What the extractor missed

One item per line, in the step-2 syntax, without the checkbox. `@path` defaults to this
file. Examples:

    N Prop:Button::onClick
    E USES_COMPONENT Function_Component:App -> Function_Component:Header@src/Header.tsx

<!-- wp6:missed -->
E USES_CUSTOM_HOOK Function_Component:Projects -> Custom_Hook:useSelectedProjectValue@src/context/selected-project-context.js # cause: llm: src/context/index.js is a barrel file that only re-exports. The hook is defined in src/context/selected-project-context.js.
E USES_CUSTOM_HOOK Function_Component:Projects -> Custom_Hook:useProjectsValue@src/context/projects-context.js # cause: llm: src/context/index.js is a barrel file that only re-exports. The hook is defined in src/context/projects-context.js.
<!-- wp6:missed-end -->

