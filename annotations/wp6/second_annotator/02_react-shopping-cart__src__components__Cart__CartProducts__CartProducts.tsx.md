# WP6 annotation — react-shopping-cart · `src/components/Cart/CartProducts/CartProducts.tsx`

<!-- wp6 v1 project=react-shopping-cart path=src/components/Cart/CartProducts/CartProducts.tsx sha=9fa56244d0f0c0d363cab744a3305c50eabc08cb graph=graph_export/react-shopping-cart/full_dump.cypherl prompt_set=72ef9f041851 -->

status: done
annotator:  annotator_2

> Guide: `docs/phase_2/ijckg-2026/annotation_guide.md`. Work top to bottom and **finish
> step 1 before you read step 2**. Set `status:` to `done` when the file is finished.

## Step 1 — Read the source, then note what you see (not scored)

List the components, hooks, props, state, handlers, contexts and routes you find, and
what each component renders and uses. Do this *before* looking at step 2.

<!-- wp6:notes -->

<!-- wp6:notes-end -->

Source at `9fa5624`:

````tsx
 1  import { ICartProduct } from 'models';
 2  import CartProduct from './CartProduct';
 3  
 4  import * as S from './style';
 5  
 6  interface IProps {
 7    products: ICartProduct[];
 8  }
 9  
10  const CartProducts = ({ products }: IProps) => {
11    return (
12      <S.Container>
13        {products?.length ? (
14          products.map((p) => <CartProduct product={p} key={p.sku} />)
15        ) : (
16          <S.CartProductsEmpty>
17            Add some products in the cart <br />
18            :)
19          </S.CartProductsEmpty>
20        )}
21      </S.Container>
22    );
23  };
24  
25  export default CartProducts;
````

## Step 2 — Review what the extractor found

Set every `[ ]` to `[y]` (correct), `[n]` (wrong) or `[?]` (unsure). An item that is
right but points at the wrong target is `[n]`; add the right one in step 3. Add
` # cause: resolution|llm|schema` or any note after an item if useful.

<!-- wp6:items -->

### LLM-extracted nodes (2)

- [y] N Function_Component:CartProducts
- [y] N Prop:CartProducts::products

### LLM-extracted edges (4)

- [y] E ACCEPTS_PROP Function_Component:CartProducts -> Prop:CartProducts::products
- [y] E DEFINED_IN Function_Component:CartProducts -> File
- [y] E PASSES_PROP Function_Component:CartProducts -> Function_Component:CartProduct@src/components/Cart/CartProducts/CartProduct/CartProduct.tsx prop=product
- [y] E USES_COMPONENT Function_Component:CartProducts -> Function_Component:CartProduct@src/components/Cart/CartProducts/CartProduct/CartProduct.tsx

### Deterministic (sanity scope) (2)

- [y] N File
- [y] E BELONGS_TO File -> Project:react-shopping-cart

<!-- wp6:items-end -->

## Step 3 — What the extractor missed

One item per line, in the step-2 syntax, without the checkbox. `@path` defaults to this
file. Examples:

    N Prop:Button::onClick
    E USES_COMPONENT Function_Component:App -> Function_Component:Header@src/Header.tsx

<!-- wp6:missed -->

<!-- wp6:missed-end -->
