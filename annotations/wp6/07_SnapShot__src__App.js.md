# WP6 annotation — SnapShot · `src/App.js`

<!-- wp6 v1 project=SnapShot path=src/App.js sha=d6ea1fd3fd74f6bbfa8794963b6743ac5be61757 graph=graph_export/SnapShot/full_dump.cypherl prompt_set=72ef9f041851 -->

status: done
annotator: annotator_1

> Guide: `docs/phase_2/ijckg-2026/annotation_guide.md`. Work top to bottom and **finish
> step 1 before you read step 2**. Set `status:` to `` when the file is finished.

## Step 1 — Read the source, then note what you see (not scored)

List the components, hooks, props, state, handlers, contexts and routes you find, and
what each component renders and uses. Do this *before* looking at step 2.

<!-- wp6:notes -->

<!-- wp6:notes-end -->

Source at `d6ea1fd`:

````js
 1  import React, { Component } from "react";
 2  import PhotoContextProvider from "./context/PhotoContext";
 3  import { HashRouter, Route, Switch, Redirect } from "react-router-dom";
 4  import Header from "./components/Header";
 5  import Item from "./components/Item";
 6  import Search from "./components/Search";
 7  import NotFound from "./components/NotFound";
 8  
 9  class App extends Component {
10    // Prevent page reload, clear input, set URL and push history on submit
11    handleSubmit = (e, history, searchInput) => {
12      e.preventDefault();
13      e.currentTarget.reset();
14      let url = `/search/${searchInput}`;
15      history.push(url);
16    };
17  
18    render() {
19      return (
20        <PhotoContextProvider>
21          <HashRouter basename="/SnapScout">
22            <div className="container">
23              <Route
24                render={props => (
25                  <Header
26                    handleSubmit={this.handleSubmit}
27                    history={props.history}
28                  />
29                )}
30              />
31              <Switch>
32                <Route
33                  exact
34                  path="/"
35                  render={() => <Redirect to="/mountain" />}
36                />
37  
38                <Route
39                  path="/mountain"
40                  render={() => <Item searchTerm="mountain" />}
41                />
42                <Route path="/beach" render={() => <Item searchTerm="beach" />} />
43                <Route path="/bird" render={() => <Item searchTerm="bird" />} />
44                <Route path="/food" render={() => <Item searchTerm="food" />} />
45                <Route
46                  path="/search/:searchInput"
47                  render={props => (
48                    <Search searchTerm={props.match.params.searchInput} />
49                  )}
50                />
51                <Route component={NotFound} />
52              </Switch>
53            </div>
54          </HashRouter>
55        </PhotoContextProvider>
56      );
57    }
58  }
59  
60  export default App;
````

## Step 2 — Review what the extractor found

Set every `[ ]` to `[y]` (correct), `[n]` (wrong) or `[?]` (unsure). An item that is
right but points at the wrong target is `[n]`; add the right one in step 3. Add
` # cause: resolution|llm|schema` or any note after an item if useful.

<!-- wp6:items -->

### LLM-extracted nodes (2)

- [y] N Class_Component:App
- [y] N EventHandler:App::handleSubmit

### LLM-extracted edges (15)

- [y] E DEFINED_IN Class_Component:App -> File
- [y] E HAS_HANDLER Class_Component:App -> EventHandler:App::handleSubmit
- [y] E PASSES_PROP Class_Component:App -> Function_Component:Header@src/components/Header.js prop=handleSubmit
- [y] E PASSES_PROP Class_Component:App -> Function_Component:Header@src/components/Header.js prop=history
- [y] E PASSES_PROP Class_Component:App -> Function_Component:Item@src/components/Item.js prop=searchTerm
- [y] E PASSES_PROP Class_Component:App -> Function_Component:Search@src/components/Search.js prop=searchTerm
- [y] E ROUTES_TO Class_Component:App -> Function_Component:Header@src/components/Header.js path='<UNKNOWN>'
- [y] E ROUTES_TO Class_Component:App -> Function_Component:Item@src/components/Item.js path=/food
- [n] E ROUTES_TO Class_Component:App -> Function_Component:NotFound@src/components/NotFound.js path='*' # cause: llm: the Route has no readable path; the guide requires path=‘<UNKNOWN>’
- [y] E ROUTES_TO Class_Component:App -> Function_Component:Search@src/components/Search.js path=/search/:searchInput
- [y] E USES_COMPONENT Class_Component:App -> Function_Component:Header@src/components/Header.js
- [y] E USES_COMPONENT Class_Component:App -> Function_Component:Item@src/components/Item.js
- [y] E USES_COMPONENT Class_Component:App -> Function_Component:NotFound@src/components/NotFound.js
- [y] E USES_COMPONENT Class_Component:App -> Function_Component:PhotoContextProvider@src/context/PhotoContext.js
- [y] E USES_COMPONENT Class_Component:App -> Function_Component:Search@src/components/Search.js

### Deterministic (sanity scope) (2)

- [y] N File
- [y] E BELONGS_TO File -> Project:snapshot

<!-- wp6:items-end -->

## Step 3 — What the extractor missed

One item per line, in the step-2 syntax, without the checkbox. `@path` defaults to this
file. Examples:

    N Prop:Button::onClick
    E USES_COMPONENT Function_Component:App -> Function_Component:Header@src/Header.tsx

<!-- wp6:missed -->
E ROUTES_TO Class_Component:App -> Function_Component:Item@src/components/Item.js path=/mountain # cause: llm 
E ROUTES_TO Class_Component:App -> Function_Component:Item@src/components/Item.js path=/beach # cause: llm 
E ROUTES_TO Class_Component:App -> Function_Component:Item@src/components/Item.js path=/bird # cause: llm 
E ROUTES_TO Class_Component:App -> Function_Component:NotFound@src/components/NotFound.js path='<UNKNOWN>' # cause: llm
<!-- wp6:missed-end -->
