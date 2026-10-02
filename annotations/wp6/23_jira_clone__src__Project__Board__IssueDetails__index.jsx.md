# WP6 annotation — jira_clone · `src/Project/Board/IssueDetails/index.jsx`

<!-- wp6 v1 project=jira_clone path=src/Project/Board/IssueDetails/index.jsx sha=26a9e77b1789fef9cb43edb5d6018cf1663cf035 graph=graph_export/jira_clone/full_dump.cypherl prompt_set=72ef9f041851 -->

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
 1  import React, { Fragment } from 'react';
 2  import PropTypes from 'prop-types';
 3  
 4  import api from 'shared/utils/api';
 5  import useApi from 'shared/hooks/api';
 6  import { PageError, CopyLinkButton, Button, AboutTooltip } from 'shared/components';
 7  
 8  import Loader from './Loader';
 9  import Type from './Type';
10  import Delete from './Delete';
11  import Title from './Title';
12  import Description from './Description';
13  import Comments from './Comments';
14  import Status from './Status';
15  import AssigneesReporter from './AssigneesReporter';
16  import Priority from './Priority';
17  import EstimateTracking from './EstimateTracking';
18  import Dates from './Dates';
19  import { TopActions, TopActionsRight, Content, Left, Right } from './Styles';
20  
21  const propTypes = {
22    issueId: PropTypes.string.isRequired,
23    projectUsers: PropTypes.array.isRequired,
24    fetchProject: PropTypes.func.isRequired,
25    updateLocalProjectIssues: PropTypes.func.isRequired,
26    modalClose: PropTypes.func.isRequired,
27  };
28  
29  const ProjectBoardIssueDetails = ({
30    issueId,
31    projectUsers,
32    fetchProject,
33    updateLocalProjectIssues,
34    modalClose,
35  }) => {
36    const [{ data, error, setLocalData }, fetchIssue] = useApi.get(`/issues/${issueId}`);
37  
38    if (!data) return <Loader />;
39    if (error) return <PageError />;
40  
41    const { issue } = data;
42  
43    const updateLocalIssueDetails = fields =>
44      setLocalData(currentData => ({ issue: { ...currentData.issue, ...fields } }));
45  
46    const updateIssue = updatedFields => {
47      api.optimisticUpdate(`/issues/${issueId}`, {
48        updatedFields,
49        currentFields: issue,
50        setLocalData: fields => {
51          updateLocalIssueDetails(fields);
52          updateLocalProjectIssues(issue.id, fields);
53        },
54      });
55    };
56  
57    return (
58      <Fragment>
59        <TopActions>
60          <Type issue={issue} updateIssue={updateIssue} />
61          <TopActionsRight>
62            <AboutTooltip
63              renderLink={linkProps => (
64                <Button icon="feedback" variant="empty" {...linkProps}>
65                  Give feedback
66                </Button>
67              )}
68            />
69            <CopyLinkButton variant="empty" />
70            <Delete issue={issue} fetchProject={fetchProject} modalClose={modalClose} />
71            <Button icon="close" iconSize={24} variant="empty" onClick={modalClose} />
72          </TopActionsRight>
73        </TopActions>
74        <Content>
75          <Left>
76            <Title issue={issue} updateIssue={updateIssue} />
77            <Description issue={issue} updateIssue={updateIssue} />
78            <Comments issue={issue} fetchIssue={fetchIssue} />
79          </Left>
80          <Right>
81            <Status issue={issue} updateIssue={updateIssue} />
82            <AssigneesReporter issue={issue} updateIssue={updateIssue} projectUsers={projectUsers} />
83            <Priority issue={issue} updateIssue={updateIssue} />
84            <EstimateTracking issue={issue} updateIssue={updateIssue} />
85            <Dates issue={issue} />
86          </Right>
87        </Content>
88      </Fragment>
89    );
90  };
91  
92  ProjectBoardIssueDetails.propTypes = propTypes;
93  
94  export default ProjectBoardIssueDetails;
````

## Step 2 — Review what the extractor found

Set every `[ ]` to `[y]` (correct), `[n]` (wrong) or `[?]` (unsure). An item that is
right but points at the wrong target is `[n]`; add the right one in step 3. Add
` # cause: resolution|llm|schema` or any note after an item if useful.

<!-- wp6:items -->

### LLM-extracted nodes (7)

- [y] N Function_Component:ProjectBoardIssueDetails
- [y] N Prop:ProjectBoardIssueDetails::fetchProject
- [y] N Prop:ProjectBoardIssueDetails::issueId
- [y] N Prop:ProjectBoardIssueDetails::modalClose
- [y] N Prop:ProjectBoardIssueDetails::projectUsers
- [y] N Prop:ProjectBoardIssueDetails::updateLocalProjectIssues
- [n] N EventHandler:ProjectBoardIssueDetails::modalClose # cause: llm: modalClose is passed as a prop to project components, not directly bound on a native JSX element

### LLM-extracted edges (50)

- [y] E ACCEPTS_PROP Function_Component:ProjectBoardIssueDetails -> Prop:ProjectBoardIssueDetails::fetchProject
- [y] E ACCEPTS_PROP Function_Component:ProjectBoardIssueDetails -> Prop:ProjectBoardIssueDetails::issueId
- [y] E ACCEPTS_PROP Function_Component:ProjectBoardIssueDetails -> Prop:ProjectBoardIssueDetails::modalClose
- [y] E ACCEPTS_PROP Function_Component:ProjectBoardIssueDetails -> Prop:ProjectBoardIssueDetails::projectUsers
- [y] E ACCEPTS_PROP Function_Component:ProjectBoardIssueDetails -> Prop:ProjectBoardIssueDetails::updateLocalProjectIssues
- [y] E DEFINED_IN Function_Component:ProjectBoardIssueDetails -> File
- [n] E HAS_HANDLER Function_Component:ProjectBoardIssueDetails -> EventHandler:ProjectBoardIssueDetails::modalClose # cause: llm: child-component callback prop, not an EventHandler owned here
- [y] E PASSES_PROP Function_Component:ProjectBoardIssueDetails -> Function_Component:AboutTooltip@src/shared/components/AboutTooltip/index.jsx prop=renderLink
- [y] E PASSES_PROP Function_Component:ProjectBoardIssueDetails -> Function_Component:Button@src/shared/components/Button/index.jsx prop=...linkProps
- [y] E PASSES_PROP Function_Component:ProjectBoardIssueDetails -> Function_Component:Button@src/shared/components/Button/index.jsx prop=icon
- [y] E PASSES_PROP Function_Component:ProjectBoardIssueDetails -> Function_Component:Button@src/shared/components/Button/index.jsx prop=iconSize
- [y] E PASSES_PROP Function_Component:ProjectBoardIssueDetails -> Function_Component:Button@src/shared/components/Button/index.jsx prop=onClick
- [y] E PASSES_PROP Function_Component:ProjectBoardIssueDetails -> Function_Component:Button@src/shared/components/Button/index.jsx prop=variant
- [y] E PASSES_PROP Function_Component:ProjectBoardIssueDetails -> Function_Component:CopyLinkButton@src/shared/components/CopyLinkButton.jsx prop=variant
- [y] E PASSES_PROP Function_Component:ProjectBoardIssueDetails -> Function_Component:ProjectBoardIssueDetailsAssigneesReporter@src/Project/Board/IssueDetails/AssigneesReporter/index.jsx prop=issue
- [y] E PASSES_PROP Function_Component:ProjectBoardIssueDetails -> Function_Component:ProjectBoardIssueDetailsAssigneesReporter@src/Project/Board/IssueDetails/AssigneesReporter/index.jsx prop=projectUsers
- [y] E PASSES_PROP Function_Component:ProjectBoardIssueDetails -> Function_Component:ProjectBoardIssueDetailsAssigneesReporter@src/Project/Board/IssueDetails/AssigneesReporter/index.jsx prop=updateIssue
- [y] E PASSES_PROP Function_Component:ProjectBoardIssueDetails -> Function_Component:ProjectBoardIssueDetailsComments@src/Project/Board/IssueDetails/Comments/index.jsx prop=fetchIssue
- [y] E PASSES_PROP Function_Component:ProjectBoardIssueDetails -> Function_Component:ProjectBoardIssueDetailsComments@src/Project/Board/IssueDetails/Comments/index.jsx prop=issue
- [y] E PASSES_PROP Function_Component:ProjectBoardIssueDetails -> Function_Component:ProjectBoardIssueDetailsDates@src/Project/Board/IssueDetails/Dates/index.jsx prop=issue
- [y] E PASSES_PROP Function_Component:ProjectBoardIssueDetails -> Function_Component:ProjectBoardIssueDetailsDelete@src/Project/Board/IssueDetails/Delete.jsx prop=fetchProject
- [y] E PASSES_PROP Function_Component:ProjectBoardIssueDetails -> Function_Component:ProjectBoardIssueDetailsDelete@src/Project/Board/IssueDetails/Delete.jsx prop=issue
- [y] E PASSES_PROP Function_Component:ProjectBoardIssueDetails -> Function_Component:ProjectBoardIssueDetailsDelete@src/Project/Board/IssueDetails/Delete.jsx prop=modalClose
- [y] E PASSES_PROP Function_Component:ProjectBoardIssueDetails -> Function_Component:ProjectBoardIssueDetailsDescription@src/Project/Board/IssueDetails/Description/index.jsx prop=issue
- [y] E PASSES_PROP Function_Component:ProjectBoardIssueDetails -> Function_Component:ProjectBoardIssueDetailsDescription@src/Project/Board/IssueDetails/Description/index.jsx prop=updateIssue
- [y] E PASSES_PROP Function_Component:ProjectBoardIssueDetails -> Function_Component:ProjectBoardIssueDetailsEstimateTracking@src/Project/Board/IssueDetails/EstimateTracking/index.jsx prop=issue
- [y] E PASSES_PROP Function_Component:ProjectBoardIssueDetails -> Function_Component:ProjectBoardIssueDetailsEstimateTracking@src/Project/Board/IssueDetails/EstimateTracking/index.jsx prop=updateIssue
- [y] E PASSES_PROP Function_Component:ProjectBoardIssueDetails -> Function_Component:ProjectBoardIssueDetailsPriority@src/Project/Board/IssueDetails/Priority/index.jsx prop=issue
- [y] E PASSES_PROP Function_Component:ProjectBoardIssueDetails -> Function_Component:ProjectBoardIssueDetailsPriority@src/Project/Board/IssueDetails/Priority/index.jsx prop=updateIssue
- [y] E PASSES_PROP Function_Component:ProjectBoardIssueDetails -> Function_Component:ProjectBoardIssueDetailsStatus@src/Project/Board/IssueDetails/Status/index.jsx prop=issue
- [y] E PASSES_PROP Function_Component:ProjectBoardIssueDetails -> Function_Component:ProjectBoardIssueDetailsStatus@src/Project/Board/IssueDetails/Status/index.jsx prop=updateIssue
- [y] E PASSES_PROP Function_Component:ProjectBoardIssueDetails -> Function_Component:ProjectBoardIssueDetailsTitle@src/Project/Board/IssueDetails/Title/index.jsx prop=issue
- [y] E PASSES_PROP Function_Component:ProjectBoardIssueDetails -> Function_Component:ProjectBoardIssueDetailsTitle@src/Project/Board/IssueDetails/Title/index.jsx prop=updateIssue
- [y] E PASSES_PROP Function_Component:ProjectBoardIssueDetails -> Function_Component:ProjectBoardIssueDetailsType@src/Project/Board/IssueDetails/Type/index.jsx prop=issue
- [y] E PASSES_PROP Function_Component:ProjectBoardIssueDetails -> Function_Component:ProjectBoardIssueDetailsType@src/Project/Board/IssueDetails/Type/index.jsx prop=updateIssue
- [y] E USES_COMPONENT Function_Component:ProjectBoardIssueDetails -> Function_Component:AboutTooltip@src/shared/components/AboutTooltip/index.jsx
- [y] E USES_COMPONENT Function_Component:ProjectBoardIssueDetails -> Function_Component:Button@src/shared/components/Button/index.jsx
- [y] E USES_COMPONENT Function_Component:ProjectBoardIssueDetails -> Function_Component:CopyLinkButton@src/shared/components/CopyLinkButton.jsx
- [y] E USES_COMPONENT Function_Component:ProjectBoardIssueDetails -> Function_Component:IssueDetailsLoader@src/Project/Board/IssueDetails/Loader.jsx
- [y] E USES_COMPONENT Function_Component:ProjectBoardIssueDetails -> Function_Component:PageError@src/shared/components/PageError/index.jsx
- [y] E USES_COMPONENT Function_Component:ProjectBoardIssueDetails -> Function_Component:ProjectBoardIssueDetailsAssigneesReporter@src/Project/Board/IssueDetails/AssigneesReporter/index.jsx
- [y] E USES_COMPONENT Function_Component:ProjectBoardIssueDetails -> Function_Component:ProjectBoardIssueDetailsComments@src/Project/Board/IssueDetails/Comments/index.jsx
- [y] E USES_COMPONENT Function_Component:ProjectBoardIssueDetails -> Function_Component:ProjectBoardIssueDetailsDates@src/Project/Board/IssueDetails/Dates/index.jsx
- [y] E USES_COMPONENT Function_Component:ProjectBoardIssueDetails -> Function_Component:ProjectBoardIssueDetailsDelete@src/Project/Board/IssueDetails/Delete.jsx
- [y] E USES_COMPONENT Function_Component:ProjectBoardIssueDetails -> Function_Component:ProjectBoardIssueDetailsDescription@src/Project/Board/IssueDetails/Description/index.jsx
- [y] E USES_COMPONENT Function_Component:ProjectBoardIssueDetails -> Function_Component:ProjectBoardIssueDetailsEstimateTracking@src/Project/Board/IssueDetails/EstimateTracking/index.jsx
- [y] E USES_COMPONENT Function_Component:ProjectBoardIssueDetails -> Function_Component:ProjectBoardIssueDetailsPriority@src/Project/Board/IssueDetails/Priority/index.jsx
- [y] E USES_COMPONENT Function_Component:ProjectBoardIssueDetails -> Function_Component:ProjectBoardIssueDetailsStatus@src/Project/Board/IssueDetails/Status/index.jsx
- [y] E USES_COMPONENT Function_Component:ProjectBoardIssueDetails -> Function_Component:ProjectBoardIssueDetailsTitle@src/Project/Board/IssueDetails/Title/index.jsx
- [y] E USES_COMPONENT Function_Component:ProjectBoardIssueDetails -> Function_Component:ProjectBoardIssueDetailsType@src/Project/Board/IssueDetails/Type/index.jsx

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
