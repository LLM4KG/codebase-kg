# WP6 annotation — jira_clone · `src/shared/components/index.js`

<!-- wp6 v1 project=jira_clone path=src/shared/components/index.js sha=26a9e77b1789fef9cb43edb5d6018cf1663cf035 graph=graph_export/jira_clone/full_dump.cypherl prompt_set=72ef9f041851 -->

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
 1  export { default as AboutTooltip } from './AboutTooltip';
 2  export { default as Avatar } from './Avatar';
 3  export { default as Button } from './Button';
 4  export { default as Breadcrumbs } from './Breadcrumbs';
 5  export { default as ConfirmModal } from './ConfirmModal';
 6  export { default as CopyLinkButton } from './CopyLinkButton';
 7  export { default as DatePicker } from './DatePicker';
 8  export { default as Form } from './Form';
 9  export { default as Icon } from './Icon';
10  export { default as Input } from './Input';
11  export { default as InputDebounced } from './InputDebounced';
12  export { default as IssueTypeIcon } from './IssueTypeIcon';
13  export { default as IssuePriorityIcon } from './IssuePriorityIcon';
14  export { default as Logo } from './Logo';
15  export { default as Modal } from './Modal';
16  export { default as PageError } from './PageError';
17  export { default as PageLoader } from './PageLoader';
18  export { default as ProjectAvatar } from './ProjectAvatar';
19  export { default as Select } from './Select';
20  export { default as Spinner } from './Spinner';
21  export { default as Textarea } from './Textarea';
22  export { default as TextEditedContent } from './TextEditedContent';
23  export { default as TextEditor } from './TextEditor';
24  export { default as Tooltip } from './Tooltip';
````

## Step 2 — Review what the extractor found

Set every `[ ]` to `[y]` (correct), `[n]` (wrong) or `[?]` (unsure). An item that is
right but points at the wrong target is `[n]`; add the right one in step 3. Add
` # cause: resolution|llm|schema` or any note after an item if useful.

<!-- wp6:items -->

### LLM-extracted nodes (0)

(none)

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
