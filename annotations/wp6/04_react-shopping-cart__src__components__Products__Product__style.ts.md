# WP6 annotation — react-shopping-cart · `src/components/Products/Product/style.ts`

<!-- wp6 v1 project=react-shopping-cart path=src/components/Products/Product/style.ts sha=9fa56244d0f0c0d363cab744a3305c50eabc08cb graph=graph_export/react-shopping-cart/full_dump.cypherl prompt_set=72ef9f041851 -->

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

````ts
  1  import styled from 'styled-components/macro';
  2  
  3  export const BuyButton = styled.button`
  4    background-color: ${({ theme }) => theme.colors.primary};
  5    color: #fff;
  6    padding: 15px 0;
  7    margin-top: 10px;
  8    cursor: pointer;
  9    width: 100%;
 10    border: 0;
 11  
 12    transition: background-color 0.2s;
 13  
 14    &:focus-visible {
 15      outline: 3px solid ${({ theme }) => theme.colors.secondary};
 16    }
 17  `;
 18  
 19  interface IImage {
 20    alt: string;
 21  }
 22  export const Image = styled.div<IImage>``;
 23  
 24  interface IContainer {
 25    sku: number | string;
 26  }
 27  export const Container = styled.div<IContainer>`
 28    position: relative;
 29    text-align: center;
 30    box-sizing: border-box;
 31    padding: 10px;
 32    margin-bottom: 30px;
 33    cursor: default;
 34    outline: none;
 35  
 36    &:focus-visible {
 37      outline: 3px solid ${({ theme }) => theme.colors.secondary};
 38    }
 39  
 40    ${Image} {
 41      width: 100%;
 42      height: 270px;
 43      position: relative;
 44      background-image: ${({ sku }) =>
 45        `url(${require(`static/products/${sku}-1-product.webp`)})`};
 46      background-repeat: no-repeat;
 47      background-size: cover;
 48      background-position: center;
 49  
 50      ::before {
 51        content: '';
 52        display: block;
 53        position: absolute;
 54        background: #eee;
 55        width: 100%;
 56        height: 100%;
 57        z-index: -1;
 58      }
 59  
 60      @media only screen and (min-width: ${({ theme: { breakpoints } }) =>
 61          breakpoints.tablet}) {
 62        height: 320px;
 63      }
 64    }
 65  
 66    &:hover {
 67      ${Image} {
 68        background-image: ${({ sku }) =>
 69          `url(${require(`static/products/${sku}-2-product.webp`)})`};
 70      }
 71  
 72      ${BuyButton} {
 73        background-color: ${({ theme }) => theme.colors.secondary};
 74      }
 75    }
 76  `;
 77  
 78  export const Stopper = styled.div`
 79    position: absolute;
 80    color: #ececec;
 81    top: 10px;
 82    right: 10px;
 83    padding: 5px;
 84    font-size: 0.6em;
 85    background-color: ${({ theme }) => theme.colors.primary};
 86    cursor: default;
 87    z-index: 1;
 88  `;
 89  
 90  export const Title = styled.p`
 91    position: relative;
 92    padding: 0 20px;
 93    height: 45px;
 94  
 95    &::before {
 96      content: '';
 97      width: 20px;
 98      height: 2px;
 99      background-color: ${({ theme }) => theme.colors.secondary};
100      position: absolute;
101      bottom: 0;
102      left: 50%;
103      margin-left: -10px;
104    }
105  `;
106  
107  export const Price = styled.div`
108    height: 60px;
109  
110    .val {
111      b {
112        font-size: 1.5em;
113        margin-left: 5px;
114      }
115    }
116  `;
117  
118  export const Val = styled.p`
119    margin: 0;
120    b {
121      font-size: 1.5em;
122      margin-left: 5px;
123    }
124  `;
125  
126  export const Installment = styled.p`
127    margin: 0;
128    color: #9c9b9b;
129  `;
````

## Step 2 — Review what the extractor found

Set every `[ ]` to `[y]` (correct), `[n]` (wrong) or `[?]` (unsure). An item that is
right but points at the wrong target is `[n]`; add the right one in step 3. Add
` # cause: resolution|llm|schema` or any note after an item if useful.

<!-- wp6:items -->

### LLM-extracted nodes (2)

- [n] N Prop:Image::alt # cause: llm: styled-component prop; styled-components are out of scope
- [n] N Prop:Container::sku # cause: llm: styled-component prop; styled-components are out of scope

### LLM-extracted edges (0)

(none)

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
