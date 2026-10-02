# WP6 annotation — jira_clone · `src/shared/components/Modal/Styles.js`

<!-- wp6 v1 project=jira_clone path=src/shared/components/Modal/Styles.js sha=26a9e77b1789fef9cb43edb5d6018cf1663cf035 graph=graph_export/jira_clone/full_dump.cypherl prompt_set=72ef9f041851 -->

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

````js
 1  import styled, { css } from 'styled-components';
 2  
 3  import { color, mixin, zIndexValues } from 'shared/utils/styles';
 4  import Icon from 'shared/components/Icon';
 5  
 6  export const ScrollOverlay = styled.div`
 7    z-index: ${zIndexValues.modal};
 8    position: fixed;
 9    top: 0;
10    left: 0;
11    height: 100%;
12    width: 100%;
13    ${mixin.scrollableY}
14  `;
15  
16  export const ClickableOverlay = styled.div`
17    min-height: 100%;
18    background: rgba(9, 30, 66, 0.54);
19    ${props => clickOverlayStyles[props.variant]}
20  `;
21  
22  const clickOverlayStyles = {
23    center: css`
24      display: flex;
25      justify-content: center;
26      align-items: center;
27      padding: 50px;
28    `,
29    aside: '',
30  };
31  
32  export const StyledModal = styled.div`
33    display: inline-block;
34    position: relative;
35    width: 100%;
36    background: #fff;
37    ${props => modalStyles[props.variant]}
38  `;
39  
40  const modalStyles = {
41    center: css`
42      max-width: ${props => props.width}px;
43      vertical-align: middle;
44      border-radius: 3px;
45      ${mixin.boxShadowMedium}
46    `,
47    aside: css`
48      min-height: 100vh;
49      max-width: ${props => props.width}px;
50      box-shadow: 0 0 20px 0 rgba(0, 0, 0, 0.15);
51    `,
52  };
53  
54  export const CloseIcon = styled(Icon)`
55    position: absolute;
56    font-size: 25px;
57    color: ${color.textMedium};
58    transition: all 0.1s;
59    ${mixin.clickable}
60    ${props => closeIconStyles[props.variant]}
61  `;
62  
63  const closeIconStyles = {
64    center: css`
65      top: 10px;
66      right: 12px;
67      padding: 3px 5px 0px 5px;
68      border-radius: 4px;
69      &:hover {
70        background: ${color.backgroundLight};
71      }
72    `,
73    aside: css`
74      top: 10px;
75      right: -30px;
76      width: 50px;
77      height: 50px;
78      padding-top: 10px;
79      border-radius: 3px;
80      text-align: center;
81      background: #fff;
82      border: 1px solid ${color.borderLightest};
83      ${mixin.boxShadowMedium};
84      &:hover {
85        color: ${color.primary};
86      }
87    `,
88  };
````

## Step 2 — Review what the extractor found

Set every `[ ]` to `[y]` (correct), `[n]` (wrong) or `[?]` (unsure). An item that is
right but points at the wrong target is `[n]`; add the right one in step 3. Add
` # cause: resolution|llm|schema` or any note after an item if useful.

<!-- wp6:items -->

### LLM-extracted nodes (4)

- [n] N Prop:ClickableOverlay::variant # cause: llm: styled-component prop; styled-components are out of scope.
- [n] N Prop:CloseIcon::variant # cause: llm: styled-component prop; styled-components are out of scope.
- [n] N Prop:StyledModal::variant # cause: llm: styled-component prop; styled-components are out of scope.
- [n] N Prop:StyledModal::width # cause: llm: styled-component prop; styled-components are out of scope.

### LLM-extracted edges (0)

(none)

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
