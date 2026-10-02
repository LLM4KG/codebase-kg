# WP6 — Annotation guide: extraction ground truth

> For the annotator. Written 19 Sep 2026. Design and rationale:
> [`wp6_annotation_plan.md`](wp6_annotation_plan.md). Files: `annotations/wp6/`, in the order to
> annotate them. Scored by WP7.

## What you are doing

The pipeline read each source file and extracted a knowledge graph. For 28 sampled files, you
decide which of the extracted items are correct and list what the pipeline missed. The result is
precision and recall for the extractor, per node type and per relationship type.

You judge **what the code says**, not what the extractor was told. When this guide and your
reading of the code disagree, follow the code and add a note.

## Protocol for each file

Work through `annotations/wp6/` in number order. The order is repo by repo, so if time runs out,
the repos you have finished are complete.

1. **Step 1 — read first, blind.** Read the whole source (it is in the file, with line numbers).
   In the notes box, list what you see: components, hooks, props, state, handlers, contexts,
   routes, and what each component renders and uses. **Do not scroll to step 2 until this is
   done.** The items below are pre-filled from the extractor's output, and reading them first
   pulls you toward agreeing with it. The notes are not scored. They exist so that you form your
   own view first.
2. **Step 2 — decide every pre-filled item.** Change each `- [ ]` to:
   - `- [y]`: correct. `[x]` is accepted as `[y]`.
   - `- [n]`: wrong. That includes "right idea, wrong target": an edge that points at the wrong
     component is `[n]`, and you add the correct edge in step 3.
   - `- [?]`: you cannot tell. Add a note saying why. `[?]` items are reported separately and
     are not counted as right or wrong.

   **Nothing is pre-ticked.** Every item needs an explicit decision, and a file with an undecided
   item counts as unfinished.
3. **Step 3 — list what is missing.** Compare your step-1 notes with step 2. Each thing that is in
   the code but not among the items goes in the missed box, one item per line, in the syntax
   below.
4. Set `status: done` and fill in `annotator:`.

Optional: add ` # ` and a note after any item. For a wrong or missed item, a cause is useful to
WP7:
- `# cause: llm`: the extraction read the code wrongly;
- `# cause: resolution`: the right thing, linked to the wrong file or not linked at all, which is
  a cross-file resolution problem (Stage 4);
- `# cause: schema`: the code has something the schema cannot express.

**Checking your file:** `uv run python -c "from src.evaluation.annotation import parse_annotation_file as p; r=p(open('<file>').read()); print(r.errors, len(r.undecided), r.complete)"`
prints any syntax errors, the number of undecided items, and whether the file is complete.

## Item syntax

One item per line. A node is `N <endpoint>`; an edge is `E <REL> <source> -> <target>`.

| Endpoint | Form | Example |
|---|---|---|
| this file | `File` | `File` |
| component, hook, context | `Label:name` | `Function_Component:Cart` |
| prop, state variable, handler | `Label:Owner::name` | `Prop:Button::onClick`, `EventHandler:Form.Field::modal.close` |
| library hook | `Library_Hook:name@source` | `Library_Hook:useState@react` |
| anything in another file | add `@path` | `Function_Component:Header@src/components/Header.tsx` |
| project, library | `Project:name`, `Library:name` | `Library:react` |

- `@path` is repo-relative (as shown in the file's title). Without it, the endpoint is in this
  file.
- Owned items (`Prop`, `State_Variable`, `EventHandler`) name their owner with `::`, the
  separator the KG uses; both sides can contain dots.
- `PASSES_PROP` ends with `prop=<name>` and `ROUTES_TO` with `path=<path>`. Quote a value that
  contains spaces or shell characters, with `'…'` or `"…"`. Pre-filled lines are already quoted:
  `path='<UNKNOWN>'`, `path='*'`.

Examples:

```
N Custom_Hook:useCart
N State_Variable:Cart::isOpen
E USES_COMPONENT Function_Component:App -> Function_Component:Cart@src/components/Cart/Cart.tsx
E PASSES_PROP Function_Component:App -> Function_Component:Cart@src/components/Cart/Cart.tsx prop=products
E USES_LIBRARY_HOOK Function_Component:Cart -> Library_Hook:useState@react
E ROUTES_TO Class_Component:App -> Function_Component:Search@src/components/Search.js path=/search/:searchInput
```

## Matching rules (how WP7 scores)

- **Nodes** match on type + name + file. Owned nodes also match on their owner.
- **Edges** match on type + both endpoints, and for `PASSES_PROP` / `ROUTES_TO` also on the prop
  name / path.
- **Attributes are out of scope.** Don't judge `isRequired`, `type`, `defaultValue`, `exportType`,
  `isInline`, `count`, `isNested`, `isLazy` or `isProtected`. An item is correct if it exists as
  written.
- **Evidence file.** An edge belongs to the file whose code states it, which is the file of its
  **source** endpoint. `App renders Cart` is annotated in `App.tsx`, not `Cart.tsx`. So in each
  file, you judge and list only:
  - nodes defined in this file;
  - edges going *out of* this file's components, hooks and `File` node.

  You never need to search other files. Judge a cross-file target from this file's imports.

## Two scopes

- **LLM-extracted (the headline).** Everything except the deterministic types below.
- **Deterministic (sanity scope).** `File`, `BELONGS_TO`, `PROVIDED_BY`. These come from a
  directory walk and a `package.json` join, not from an LLM, and should be perfect. They are
  scored separately so they don't inflate the headline. They're quick: tick them unless something
  is plainly wrong.
- **Not annotated.** `Project`, `Library` and `DEPENDS_ON` are package-level; WP7 checks them
  against `package.json` by script. `IMPORTS` is in the schema but the pipeline never creates it,
  so don't list missing `IMPORTS` edges.

## What counts, per type

These are the extractor's own definitions (the prompts in `prompts/`). One example that counts
(✓) and one that doesn't (✗) for each.

### Nodes

**Function_Component**: a PascalCase function or arrow function that returns JSX, or that is used
as `<Name/>` in the same file.
- ✓ `const Cart = () => <S.Container>…</S.Container>`
- ✗ `const formatPrice = (x) => …`: a helper, not a component. A styled-component
  (`const Button = styled.button\`…\``) is not a component either: styling is out of scope in the
  schema. If the extractor lists one, mark it `[n] # cause: llm`.

**Class_Component**: a class that extends `React.Component` / `Component` / `PureComponent`.
- ✓ `class App extends Component { render() { … } }`
- ✗ a class that doesn't extend a React component class.

**Custom_Hook**: a function **defined in this file** whose name matches `use[A-Z]…`. JSX isn't
required.
- ✓ `const useCart = () => { … }`
- ✗ a call to `useCart()` in a component: that's usage (`USES_CUSTOM_HOOK`), not a definition.

**Context**: a `createContext(…)` / `React.createContext(…)` call.
- ✓ `const CartContext = createContext<ICartContext | undefined>(undefined)`
- ✗ `useContext(CartContext)` or `<CartContext.Provider>`: those are edges.

**Prop**: a prop a component **accepts**. Evidence is destructured parameters, `props.x`,
`this.props.x`, PropTypes or a TypeScript props type. The owner is the receiving component.
- ✓ `const Checkbox = ({ label, handleOnChange }) =>` → `Prop:Checkbox::label`,
  `Prop:Checkbox::handleOnChange`
- ✗ `children`, `key`, `ref` and spread `...rest`. `children` counts only when explicitly
  declared in PropTypes or a TS type.
- ✗ a prop of a **styled-component** (`export const Image = styled.div<IImage>` with
  `interface IImage { alt: string }`). The owner is not a component, so the prop can't be one of
  its props. The extractor does produce these (for example in `Product/style.ts` and
  `Modal/Styles.js`): mark them `[n] # cause: llm`.

**State_Variable**: one per `useState` / `useReducer` call in a function component or custom hook
(`const [isOpen, setIsOpen] = useState(false)` → `State_Variable:Cart::isOpen`). For a class
component, its `this.state` fields, linked by `DECLARES_CLASS_STATE`.
- ✓ `const [products, setProducts] = useState([])`
- ✗ `useRef`, `useMemo` or plain `let` variables.

**EventHandler**: a function referenced in a JSX **event attribute** (`onClick`, `onChange`,
`onSubmit`, `onKeyDown` …) of an element the component renders. Its name is the function's name;
an inline arrow is named `inline_<eventType>` (`inline_onClick`). A handler bound to two events
is one node per binding.
- ✓ `<button onClick={handleCheckout}>` → `EventHandler:Cart::handleCheckout`
- ✗ a function passed down as a **prop** to a child component
  (`<AddCategoryForm submitHandler={onSubmitNewCategory}/>`). By the extractor's rule this is a
  prop, not a handler. Don't list it as a missed handler; if you think the schema should model
  it, add `# cause: schema` to a note. (Known gap G2 in `schema_coverage.md`.)

**Library_Hook** is not annotated as a node. Judge it through the `USES_LIBRARY_HOOK` edge: the
hook's name and its library source must both be right.

### Edges (source → target)

**DEFINED_IN** (component or custom hook → `File`): one per component or hook defined here.
- ✓ `E DEFINED_IN Function_Component:Cart -> File`

**RENDERS_ROOT_COMPONENT** (`File` → root component): only in the app's entry file, for
`ReactDOM.render(<App/>, …)`, `createRoot(…).render(<App/>)` or a bare `render(<App/>)`.
- ✓ `E RENDERS_ROOT_COMPONENT File -> Function_Component:App@src/App.jsx` in `src/index.jsx`
- ✗ any other file.

**USES_COMPONENT** (component → **project** component it renders): every PascalCase JSX tag
that is a component of this repo. This includes conditional rendering, `.map()`, ternaries, and
components passed as prop values (`<Route component={Search}/>`).
- ✓ `<CartProducts products={products}/>` in `Cart` → `… -> Function_Component:CartProducts@…`
- ✗ HTML tags, `Fragment` / `Suspense` / `StrictMode`, **library components** (`<Link>`,
  `<Route>`, `<Provider>`: they have no node, so the edge can't exist), and styled wrappers
  (`<S.Container>`).

**PASSES_PROP** (component → project component, `prop=<name>`): one per attribute passed at a
`USES_COMPONENT` site. A spread is written as its expression (`prop=...props`).
- ✓ `<CartProducts products={products}/>` → `prop=products`
- ✗ `key`, `ref`, and `children` as nested JSX (only an explicit `children={…}` counts).

**ACCEPTS_PROP** (component → its `Prop`): one per `Prop` node, from its owner.

**USES_LIBRARY_HOOK** (component or custom hook → `Library_Hook:name@library`): a hook imported
from a package (`react`, `react-redux`, `react-router-dom` …), called in this component or hook.
One edge per hook, however many calls.
- ✓ `useState` imported from `react` → `Library_Hook:useState@react`
- ✗ a project hook: that's `USES_CUSTOM_HOOK`.

**USES_CUSTOM_HOOK** (component or custom hook → `Custom_Hook@definition file`): a call to a hook
defined in this repo. The target is the file that **defines** it, past any barrel `index.ts`
re-export.
- ✓ `useCart()` imported from `contexts/cart-context` → `Custom_Hook:useCart@src/contexts/cart-context/useCart.ts`
- ✗ a pointer at the barrel file `…/cart-context/index.ts`. Mark it `[n] # cause: resolution`
  and add the right edge.

**DECLARES_STATE** (function component or custom hook → `State_Variable`): one per state
variable. **DECLARES_CLASS_STATE** is the class-component version (no repo in the sample has any).

**PROVIDES_CONTEXT** (component → `Context`): the component renders `<XContext.Provider>`.
**CONSUMES_CONTEXT** (component or custom hook → `Context`): **direct** use only, meaning
`useContext(X)`, `static contextType = X` or `<X.Consumer>`.
- ✓ `useCartContext` hook calling `useContext(CartContext)` → consumes `CartContext`
- ✗ a component that calls `useCartContext()`: it uses the hook, and consumes nothing
  directly.

**ROUTES_TO** (component declaring the routes → target component, `path=<full path>`): each
`<Route>` (React Router), with nested paths composed (`/dashboard` + `settings` →
`/dashboard/settings`). A route with no readable path (for example a layout route) is written `path='<UNKNOWN>'`.

**HAS_HANDLER** (component → its `EventHandler`): one per handler node, from its owner.

**BELONGS_TO** (`File` → `Project`) and **PROVIDED_BY** (`Library_Hook` → `Library`):
deterministic; confirm and move on.

## Common cases

- **Same name, different file.** A child with a common name (`Button`, `Modal`) must point at
  the file this file actually imports it from. If the target file is wrong, the edge is `[n]`
  with `# cause: resolution`, and the right edge is missed.
- **A node you'd split or merge differently.** Follow the definitions above, not taste. For
  example, a component defined inside another component is still its own component if it is
  PascalCase and returns JSX.
- **Compound components** (`Form.Field = …`) keep the dotted name the code uses.
- **Out of scope in the schema:** styled-components, CSS, tests, build configuration, HOCs (see
  the schema doc, §5). Don't list their absence as missed. If the extractor produced one, mark
  it `[n]`.
- **A file with no items** (barrels, style files, utilities; one per repo is sampled on purpose):
  confirm the deterministic items and check that there really is nothing to add. That file
  measures whether the extractor missed a whole file.

## Scope of the set

| | |
|---|---|
| Files | 28: react-shopping-cart 6, SnapShot 5, Todoist 5, TakeNote 6, Jira Clone 6 (5 of them, one per repo, in the no-item stratum) |
| Items to decide | 112 LLM nodes, 254 LLM edges, 78 deterministic |
| Source to read | ≈ 1,800 lines |
| Second annotator | 4 files in `annotations/wp6/second_annotator/` (one per repo, first four repos). Annotated independently, without seeing the first annotator's file, for agreement |

The protocol is **corrected draft**: the items are pre-filled from the extractor's output. That
biases recall upward, because a missed item has to be noticed unprompted. Step 1 is the
mitigation, and WP7 states the bias.
