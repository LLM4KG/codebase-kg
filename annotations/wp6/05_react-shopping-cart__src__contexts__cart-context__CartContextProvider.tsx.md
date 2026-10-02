# WP6 annotation — react-shopping-cart · `src/contexts/cart-context/CartContextProvider.tsx`

<!-- wp6 v1 project=react-shopping-cart path=src/contexts/cart-context/CartContextProvider.tsx sha=9fa56244d0f0c0d363cab744a3305c50eabc08cb graph=graph_export/react-shopping-cart/full_dump.cypherl prompt_set=72ef9f041851 -->

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
 2  import { ICartProduct, ICartTotal } from 'models';
 3  
 4  export interface ICartContext {
 5    isOpen: boolean;
 6    setIsOpen(state: boolean): void;
 7    products: ICartProduct[];
 8    setProducts(products: ICartProduct[]): void;
 9    total: ICartTotal;
10    setTotal(products: any): void;
11  }
12  
13  const CartContext = createContext<ICartContext | undefined>(undefined);
14  const useCartContext = (): ICartContext => {
15    const context = useContext(CartContext);
16  
17    if (!context) {
18      throw new Error('useCartContext must be used within a CartProvider');
19    }
20  
21    return context;
22  };
23  
24  const totalInitialValues = {
25    productQuantity: 0,
26    installments: 0,
27    totalPrice: 0,
28    currencyId: 'USD',
29    currencyFormat: '$',
30  };
31  
32  const CartProvider: FC = (props) => {
33    const [isOpen, setIsOpen] = useState(false);
34    const [products, setProducts] = useState<ICartProduct[]>([]);
35    const [total, setTotal] = useState<ICartTotal>(totalInitialValues);
36  
37    const CartContextValue: ICartContext = {
38      isOpen,
39      setIsOpen,
40      products,
41      setProducts,
42      total,
43      setTotal,
44    };
45  
46    return <CartContext.Provider value={CartContextValue} {...props} />;
47  };
48  
49  export { CartProvider, useCartContext };
````

## Step 2 — Review what the extractor found

Set every `[ ]` to `[y]` (correct), `[n]` (wrong) or `[?]` (unsure). An item that is
right but points at the wrong target is `[n]`; add the right one in step 3. Add
` # cause: resolution|llm|schema` or any note after an item if useful.

<!-- wp6:items -->

### LLM-extracted nodes (6)

- [y] N Function_Component:CartProvider
- [y] N Custom_Hook:useCartContext
- [y] N Context:CartContext
- [y] N State_Variable:CartProvider::isOpen
- [y] N State_Variable:CartProvider::products
- [y] N State_Variable:CartProvider::total

### LLM-extracted edges (9)

- [y] E CONSUMES_CONTEXT Custom_Hook:useCartContext -> Context:CartContext
- [y] E DECLARES_STATE Function_Component:CartProvider -> State_Variable:CartProvider::isOpen
- [y] E DECLARES_STATE Function_Component:CartProvider -> State_Variable:CartProvider::products
- [y] E DECLARES_STATE Function_Component:CartProvider -> State_Variable:CartProvider::total
- [y] E DEFINED_IN Function_Component:CartProvider -> File
- [y] E DEFINED_IN Custom_Hook:useCartContext -> File
- [y] E PROVIDES_CONTEXT Function_Component:CartProvider -> Context:CartContext
- [y] E USES_LIBRARY_HOOK Function_Component:CartProvider -> Library_Hook:useState@react
- [y] E USES_LIBRARY_HOOK Custom_Hook:useCartContext -> Library_Hook:useContext@react

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
