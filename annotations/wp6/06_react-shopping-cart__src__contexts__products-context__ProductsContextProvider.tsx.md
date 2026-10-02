# WP6 annotation — react-shopping-cart · `src/contexts/products-context/ProductsContextProvider.tsx`

<!-- wp6 v1 project=react-shopping-cart path=src/contexts/products-context/ProductsContextProvider.tsx sha=9fa56244d0f0c0d363cab744a3305c50eabc08cb graph=graph_export/react-shopping-cart/full_dump.cypherl prompt_set=72ef9f041851 -->

status: done
annotator: annotator_1

> Guide: `docs/phase_2/ijckg-2026/annotation_guide.md`. Work top to bottom and **finish
> step 1 before you read step 2**. Set `status:` to `done` when the file is finished.

## Step 1 — Read the source, then note what you see (not scored)

List the components, hooks, props, state, handlers, contexts and routes you find, and
what each component renders and uses. Do this *before* looking at step 2.

<!-- wp6:notes -->

<!-- wp6:notes-end -->

Source at `9fa5624`:

````tsx
 1  import { createContext, useContext, FC, useState } from 'react';
 2  
 3  import { IProduct } from 'models';
 4  
 5  export interface IProductsContext {
 6    isFetching: boolean;
 7    setIsFetching(state: boolean): void;
 8    products: IProduct[];
 9    setProducts(products: IProduct[]): void;
10    filters: string[];
11    setFilters(filters: string[]): void;
12  }
13  
14  const ProductsContext = createContext<IProductsContext | undefined>(undefined);
15  const useProductsContext = (): IProductsContext => {
16    const context = useContext(ProductsContext);
17  
18    if (!context) {
19      throw new Error(
20        'useProductsContext must be used within a ProductsProvider'
21      );
22    }
23  
24    return context;
25  };
26  
27  const ProductsProvider: FC = (props) => {
28    const [isFetching, setIsFetching] = useState(false);
29    const [products, setProducts] = useState<IProduct[]>([]);
30    const [filters, setFilters] = useState<string[]>([]);
31  
32    const ProductContextValue: IProductsContext = {
33      isFetching,
34      setIsFetching,
35      products,
36      setProducts,
37      filters,
38      setFilters,
39    };
40  
41    return <ProductsContext.Provider value={ProductContextValue} {...props} />;
42  };
43  
44  export { ProductsProvider, useProductsContext };
````

## Step 2 — Review what the extractor found

Set every `[ ]` to `[y]` (correct), `[n]` (wrong) or `[?]` (unsure). An item that is
right but points at the wrong target is `[n]`; add the right one in step 3. Add
` # cause: resolution|llm|schema` or any note after an item if useful.

<!-- wp6:items -->

### LLM-extracted nodes (6)

- [y] N Function_Component:ProductsProvider
- [y] N Custom_Hook:useProductsContext
- [y] N Context:ProductsContext
- [y] N State_Variable:ProductsProvider::filters
- [y] N State_Variable:ProductsProvider::isFetching
- [y] N State_Variable:ProductsProvider::products

### LLM-extracted edges (9)

- [y] E CONSUMES_CONTEXT Custom_Hook:useProductsContext -> Context:ProductsContext
- [y] E DECLARES_STATE Function_Component:ProductsProvider -> State_Variable:ProductsProvider::filters
- [y] E DECLARES_STATE Function_Component:ProductsProvider -> State_Variable:ProductsProvider::isFetching
- [y] E DECLARES_STATE Function_Component:ProductsProvider -> State_Variable:ProductsProvider::products
- [y] E DEFINED_IN Function_Component:ProductsProvider -> File
- [y] E DEFINED_IN Custom_Hook:useProductsContext -> File
- [y] E PROVIDES_CONTEXT Function_Component:ProductsProvider -> Context:ProductsContext
- [y] E USES_LIBRARY_HOOK Function_Component:ProductsProvider -> Library_Hook:useState@react
- [y] E USES_LIBRARY_HOOK Custom_Hook:useProductsContext -> Library_Hook:useContext@react

### Deterministic (sanity scope) (4)

- [y] N File
- [y] E BELONGS_TO File -> Project:react-shopping-cart
- [y] E PROVIDED_BY Library_Hook:useContext@react -> Library:react
- [y] E PROVIDED_BY Library_Hook:useState@react -> Library:react

<!-- wp6:items-end -->

## Step 3 — What the extractor missed

One item per line, in the step-2 syntax, without the checkbox. `@path` defaults to this
file. Examples:

    N Prop:Button::onClick
    E USES_COMPONENT Function_Component:App -> Function_Component:Header@src/Header.tsx

<!-- wp6:missed -->

<!-- wp6:missed-end -->
