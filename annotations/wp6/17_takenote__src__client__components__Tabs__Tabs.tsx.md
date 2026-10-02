# WP6 annotation — takenote · `src/client/components/Tabs/Tabs.tsx`

<!-- wp6 v1 project=takenote path=src/client/components/Tabs/Tabs.tsx sha=e0eddbb9a21ae4cf4c4c7c183f29cfd666e08331 graph=graph_export/takenote/full_dump.cypherl prompt_set=72ef9f041851 -->

status: done
annotator: annotator_1

> Guide: `docs/phase_2/ijckg-2026/annotation_guide.md`. Work top to bottom and **finish
> step 1 before you read step 2**. Set `status:` to `done` when the file is finished.

## Step 1 — Read the source, then note what you see (not scored)

List the components, hooks, props, state, handlers, contexts and routes you find, and
what each component renders and uses. Do this *before* looking at step 2.

<!-- wp6:notes -->

<!-- wp6:notes-end -->

Source at `e0eddbb`:

````tsx
 1  import React, { Fragment, useState } from 'react'
 2  
 3  import { Tab } from './Tab'
 4  
 5  export interface TabsProps {
 6    children: JSX.Element[]
 7  }
 8  
 9  export const Tabs: React.FC<TabsProps> = ({ children }) => {
10    const [activeTab, setActiveTab] = useState('Preferences')
11  
12    return (
13      <div className="tabs">
14        <nav className="tab-list">
15          {children.map((child) => {
16            const { label, icon } = child.props
17  
18            return (
19              <Tab
20                icon={icon}
21                activeTab={activeTab}
22                key={label}
23                label={label}
24                onClick={setActiveTab}
25              />
26            )
27          })}
28        </nav>
29        <div className="tab-content">
30          {children.map((child) => {
31            if (child.props.label !== activeTab) return
32  
33            return (
34              <Fragment key={`${child.props.label}-panel`}>
35                <h3>{child.props.label}</h3>
36                {child.props.children}
37              </Fragment>
38            )
39          })}
40        </div>
41      </div>
42    )
43  }
````

## Step 2 — Review what the extractor found

Set every `[ ]` to `[y]` (correct), `[n]` (wrong) or `[?]` (unsure). An item that is
right but points at the wrong target is `[n]`; add the right one in step 3. Add
` # cause: resolution|llm|schema` or any note after an item if useful.

<!-- wp6:items -->

### LLM-extracted nodes (2)

- [y] N Function_Component:Tabs
- [y] N State_Variable:Tabs::activeTab

### LLM-extracted edges (8)

- [y] E DECLARES_STATE Function_Component:Tabs -> State_Variable:Tabs::activeTab
- [y] E DEFINED_IN Function_Component:Tabs -> File
- [y] E PASSES_PROP Function_Component:Tabs -> Function_Component:Tab@src/client/components/Tabs/Tab.tsx prop=activeTab
- [y] E PASSES_PROP Function_Component:Tabs -> Function_Component:Tab@src/client/components/Tabs/Tab.tsx prop=icon
- [y] E PASSES_PROP Function_Component:Tabs -> Function_Component:Tab@src/client/components/Tabs/Tab.tsx prop=label
- [y] E PASSES_PROP Function_Component:Tabs -> Function_Component:Tab@src/client/components/Tabs/Tab.tsx prop=onClick
- [y] E USES_COMPONENT Function_Component:Tabs -> Function_Component:Tab@src/client/components/Tabs/Tab.tsx
- [y] E USES_LIBRARY_HOOK Function_Component:Tabs -> Library_Hook:useState@react

### Deterministic (sanity scope) (3)

- [y] N File
- [y] E BELONGS_TO File -> Project:takenote
- [y] E PROVIDED_BY Library_Hook:useState@react -> Library:react

<!-- wp6:items-end -->

## Step 3 — What the extractor missed

One item per line, in the step-2 syntax, without the checkbox. `@path` defaults to this
file. Examples:

    N Prop:Button::onClick
    E USES_COMPONENT Function_Component:App -> Function_Component:Header@src/Header.tsx

<!-- wp6:missed -->
N Prop:Tabs::children # cause: llm
E ACCEPTS_PROP Function_Component:Tabs -> Prop:Tabs::children # cause: llm
<!-- wp6:missed-end -->
