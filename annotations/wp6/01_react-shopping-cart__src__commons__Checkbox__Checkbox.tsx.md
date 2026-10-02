# WP6 annotation — react-shopping-cart · `src/commons/Checkbox/Checkbox.tsx`

<!-- wp6 v1 project=react-shopping-cart path=src/commons/Checkbox/Checkbox.tsx sha=9fa56244d0f0c0d363cab744a3305c50eabc08cb graph=graph_export/react-shopping-cart/full_dump.cypherl prompt_set=72ef9f041851 -->

status: done
annotator:annotator_1

> Guide: `docs/phase_2/ijckg-2026/annotation_guide.md`. Work top to bottom and **finish
> step 1 before you read step 2**. Set `status:` to `done` when the file is finished.

## Step 1 — Read the source, then note what you see (not scored)

List the components, hooks, props, state, handlers, contexts and routes you find, and
what each component renders and uses. Do this *before* looking at step 2.

<!-- wp6:notes -->

<!-- wp6:notes-end -->

Source at `9fa5624`:

````tsx
 1  import { useState } from 'react';
 2  
 3  interface IProps {
 4    className?: string;
 5    label: string;
 6    handleOnChange(label: string): void;
 7  }
 8  
 9  const Checkbox = ({ className, label, handleOnChange }: IProps) => {
10    const [isChecked, setIsChecked] = useState(false);
11  
12    const toggleCheckboxChange = () => {
13      setIsChecked(!isChecked);
14      handleOnChange(label);
15    };
16  
17    return (
18      <div className={className}>
19        <label>
20          <input
21            type="checkbox"
22            value={label}
23            checked={isChecked}
24            onChange={toggleCheckboxChange}
25            data-testid="checkbox"
26          />
27  
28          <span className="checkmark">{label}</span>
29        </label>
30      </div>
31    );
32  };
33  
34  export default Checkbox;
````

## Step 2 — Review what the extractor found

Set every `[ ]` to `[y]` (correct), `[n]` (wrong) or `[?]` (unsure). An item that is
right but points at the wrong target is `[n]`; add the right one in step 3. Add
` # cause: resolution|llm|schema` or any note after an item if useful.

<!-- wp6:items -->

### LLM-extracted nodes (6)

- [y] N Function_Component:Checkbox
- [y] N Prop:Checkbox::className
- [y] N Prop:Checkbox::handleOnChange
- [y] N Prop:Checkbox::label
- [y] N State_Variable:Checkbox::isChecked
- [y] N EventHandler:Checkbox::toggleCheckboxChange

### LLM-extracted edges (7)

- [y] E ACCEPTS_PROP Function_Component:Checkbox -> Prop:Checkbox::className
- [y] E ACCEPTS_PROP Function_Component:Checkbox -> Prop:Checkbox::handleOnChange
- [y] E ACCEPTS_PROP Function_Component:Checkbox -> Prop:Checkbox::label
- [y] E DECLARES_STATE Function_Component:Checkbox -> State_Variable:Checkbox::isChecked
- [y] E DEFINED_IN Function_Component:Checkbox -> File
- [y] E HAS_HANDLER Function_Component:Checkbox -> EventHandler:Checkbox::toggleCheckboxChange
- [y] E USES_LIBRARY_HOOK Function_Component:Checkbox -> Library_Hook:useState@react

### Deterministic (sanity scope) (3)

- [y] N File
- [y] E BELONGS_TO File -> Project:react-shopping-cart
- [y] E PROVIDED_BY Library_Hook:useState@react -> Library:react

<!-- wp6:items-end -->

## Step 3 — What the extractor missed

One item per line, in the step-2 syntax, without the checkbox. `@path` defaults to this
file. Examples:

    N Prop:Button::onClick
    E USES_COMPONENT Function_Component:App -> Function_Component:Header@src/Header.tsx

<!-- wp6:missed -->

<!-- wp6:missed-end -->
