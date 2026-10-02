# WP6 annotation — jira_clone · `src/shared/components/AboutTooltip/index.jsx`

<!-- wp6 v1 project=jira_clone path=src/shared/components/AboutTooltip/index.jsx sha=26a9e77b1789fef9cb43edb5d6018cf1663cf035 graph=graph_export/jira_clone/full_dump.cypherl prompt_set=72ef9f041851 -->

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
 3  import Button from 'shared/components/Button';
 4  import Tooltip from 'shared/components/Tooltip';
 5  
 6  import feedbackImage from './assets/feedback.png';
 7  import { FeedbackDropdown, FeedbackImageCont, FeedbackImage, FeedbackParagraph } from './Styles';
 8  
 9  const AboutTooltip = tooltipProps => (
10    <Tooltip
11      width={300}
12      {...tooltipProps}
13      renderContent={() => (
14        <FeedbackDropdown>
15          <FeedbackImageCont>
16            <FeedbackImage src={feedbackImage} alt="Give feedback" />
17          </FeedbackImageCont>
18  
19          <FeedbackParagraph>
20            This simplified Jira clone is built with React on the front-end and Node/TypeScript on the
21            back-end.
22          </FeedbackParagraph>
23  
24          <FeedbackParagraph>
25            {'Read more on my website or reach out via '}
26            <a href="mailto:ivor@codetree.co">
27              <strong>ivor@codetree.co</strong>
28            </a>
29          </FeedbackParagraph>
30  
31          <a href="https://getivor.com/" target="_blank" rel="noreferrer noopener">
32            <Button variant="primary">Visit Website</Button>
33          </a>
34  
35          <a href="https://github.com/oldboyxx/jira_clone" target="_blank" rel="noreferrer noopener">
36            <Button style={{ marginLeft: 10 }} icon="github">
37              Github Repo
38            </Button>
39          </a>
40        </FeedbackDropdown>
41      )}
42    />
43  );
44  
45  export default AboutTooltip;
````

## Step 2 — Review what the extractor found

Set every `[ ]` to `[y]` (correct), `[n]` (wrong) or `[?]` (unsure). An item that is
right but points at the wrong target is `[n]`; add the right one in step 3. Add
` # cause: resolution|llm|schema` or any note after an item if useful.

<!-- wp6:items -->

### LLM-extracted nodes (2)

- [y] N Function_Component:AboutTooltip
- [n] N Prop:AboutTooltip::tooltipProps # cause: llm: tooltipProps is not a prop. It's the name the component gives to its entire props object.

### LLM-extracted edges (10)

- [n] E ACCEPTS_PROP Function_Component:AboutTooltip -> Prop:AboutTooltip::tooltipProps # cause: llm: no individual prop named tooltipProps is established
- [y] E DEFINED_IN Function_Component:AboutTooltip -> File
- [y] E PASSES_PROP Function_Component:AboutTooltip -> Function_Component:Button@src/shared/components/Button/index.jsx prop=icon
- [y] E PASSES_PROP Function_Component:AboutTooltip -> Function_Component:Button@src/shared/components/Button/index.jsx prop=style
- [y] E PASSES_PROP Function_Component:AboutTooltip -> Function_Component:Button@src/shared/components/Button/index.jsx prop=variant
- [y] E PASSES_PROP Function_Component:AboutTooltip -> Function_Component:Tooltip@src/shared/components/Tooltip/index.jsx prop=...tooltipProps
- [y] E PASSES_PROP Function_Component:AboutTooltip -> Function_Component:Tooltip@src/shared/components/Tooltip/index.jsx prop=renderContent
- [y] E PASSES_PROP Function_Component:AboutTooltip -> Function_Component:Tooltip@src/shared/components/Tooltip/index.jsx prop=width
- [y] E USES_COMPONENT Function_Component:AboutTooltip -> Function_Component:Button@src/shared/components/Button/index.jsx
- [y] E USES_COMPONENT Function_Component:AboutTooltip -> Function_Component:Tooltip@src/shared/components/Tooltip/index.jsx

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
