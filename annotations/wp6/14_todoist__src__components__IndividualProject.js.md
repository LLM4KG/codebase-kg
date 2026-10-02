# WP6 annotation — todoist · `src/components/IndividualProject.js`

<!-- wp6 v1 project=todoist path=src/components/IndividualProject.js sha=f998b9af73a1d533e52a9a3f5545216904faf077 graph=graph_export/todoist/full_dump.cypherl prompt_set=72ef9f041851 -->

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
 2  import { FaTrashAlt } from 'react-icons/fa';
 3  import PropTypes from 'prop-types';
 4  import { useProjectsValue, useSelectedProjectValue } from '../context';
 5  import { firebase } from '../firebase';
 6  
 7  export const IndividualProject = ({ project }) => {
 8    const [showConfirm, setShowConfirm] = useState(false);
 9    const { projects, setProjects } = useProjectsValue();
10    const { setSelectedProject } = useSelectedProjectValue();
11  
12    const deleteProject = (docId) => {
13      firebase
14        .firestore()
15        .collection('projects')
16        .doc(docId)
17        .delete()
18        .then(() => {
19          setProjects([...projects]);
20          setSelectedProject('INBOX');
21        });
22    };
23  
24    return (
25      <>
26        <span className="sidebar__dot">•</span>
27        <span className="sidebar__project-name">{project.name}</span>
28        <span
29          className="sidebar__project-delete"
30          data-testid="delete-project"
31          onClick={() => setShowConfirm(!showConfirm)}
32          onKeyDown={(e) => {
33            if (e.key === 'Enter') setShowConfirm(!showConfirm);
34          }}
35          tabIndex={0}
36          role="button"
37          aria-label="Confirm deletion of project"
38        >
39          <FaTrashAlt />
40          {showConfirm && (
41            <div className="project-delete-modal">
42              <div className="project-delete-modal__inner">
43                <p>Are you sure you want to delete this project?</p>
44                <button
45                  type="button"
46                  onClick={() => deleteProject(project.docId)}
47                >
48                  Delete
49                </button>
50                <span
51                  onClick={() => setShowConfirm(!showConfirm)}
52                  onKeyDown={(e) => {
53                    if (e.key === 'Enter') setShowConfirm(!showConfirm);
54                  }}
55                  tabIndex={0}
56                  role="button"
57                  aria-label="Cancel adding project, do not delete"
58                >
59                  Cancel
60                </span>
61              </div>
62            </div>
63          )}
64        </span>
65      </>
66    );
67  };
68  
69  IndividualProject.propTypes = {
70    project: PropTypes.object.isRequired,
71  };
````

## Step 2 — Review what the extractor found

Set every `[ ]` to `[y]` (correct), `[n]` (wrong) or `[?]` (unsure). An item that is
right but points at the wrong target is `[n]`; add the right one in step 3. Add
` # cause: resolution|llm|schema` or any note after an item if useful.

<!-- wp6:items -->

### LLM-extracted nodes (8)

- [y] N Function_Component:IndividualProject
- [y] N Prop:IndividualProject::project
- [y] N State_Variable:IndividualProject::showConfirm
- [y] N EventHandler:IndividualProject::inline_onClick
- [y] N EventHandler:IndividualProject::inline_onClick_2
- [y] N EventHandler:IndividualProject::inline_onClick_3
- [y] N EventHandler:IndividualProject::inline_onKeyDown
- [y] N EventHandler:IndividualProject::inline_onKeyDown_2

### LLM-extracted edges (9)

- [y] E ACCEPTS_PROP Function_Component:IndividualProject -> Prop:IndividualProject::project
- [y] E DECLARES_STATE Function_Component:IndividualProject -> State_Variable:IndividualProject::showConfirm
- [y] E DEFINED_IN Function_Component:IndividualProject -> File
- [y] E HAS_HANDLER Function_Component:IndividualProject -> EventHandler:IndividualProject::inline_onClick
- [y] E HAS_HANDLER Function_Component:IndividualProject -> EventHandler:IndividualProject::inline_onClick_2
- [y] E HAS_HANDLER Function_Component:IndividualProject -> EventHandler:IndividualProject::inline_onClick_3
- [y] E HAS_HANDLER Function_Component:IndividualProject -> EventHandler:IndividualProject::inline_onKeyDown
- [y] E HAS_HANDLER Function_Component:IndividualProject -> EventHandler:IndividualProject::inline_onKeyDown_2
- [y] E USES_LIBRARY_HOOK Function_Component:IndividualProject -> Library_Hook:useState@react

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
E USES_CUSTOM_HOOK Function_Component:IndividualProject -> Custom_Hook:useProjectsValue@src/context/projects-context.js # cause: llm: src/context/index.js is a barrel file that only re-exports. The hook is defined in src/context/projects-context.js. 
E USES_CUSTOM_HOOK Function_Component:IndividualProject -> Custom_Hook:useSelectedProjectValue@src/context/selected-project-context.js # cause: llm: src/context/index.js is a barrel file that only re-exports. The hook is defined in src/context/selected-project-context.js.
<!-- wp6:missed-end -->
