"""Tests for cross_file resolution functions."""

import pytest

from src.extraction.cross_file import (
    resolve_alias,
    resolve_relative_import,
    expand_extensions,
    _extract_rendered_component,
)


class TestResolveAlias:
    def test_basic_alias(self):
        aliases = {"@": "src/client", "@resources": "src/resources"}
        assert resolve_alias("@/components/NoteList", aliases) == "src/client/components/NoteList"

    def test_longest_prefix_wins(self):
        aliases = {"@": "src/client", "@resources": "src/resources"}
        assert resolve_alias("@resources/LabelText", aliases) == "src/resources/LabelText"

    def test_no_match_returns_none(self):
        aliases = {"@": "src/client"}
        assert resolve_alias("react-router-dom", aliases) is None

    def test_empty_aliases_returns_none(self):
        assert resolve_alias("@/utils/helper", {}) is None

    def test_exact_alias_match(self):
        aliases = {"@": "src/client"}
        assert resolve_alias("@", aliases) == "src/client"

    def test_alias_no_partial_name_match(self):
        """'@res' should not match '@resources' prefix."""
        aliases = {"@resources": "src/resources"}
        assert resolve_alias("@res/foo", aliases) is None


class TestResolveRelativeImport:
    def test_same_dir(self):
        result = resolve_relative_import("./ProductCard", "src/components/ProductList.jsx")
        assert result == "src/components/ProductCard"

    def test_parent_dir(self):
        result = resolve_relative_import("../hooks/useCart", "src/components/Cart.jsx")
        assert result == "src/hooks/useCart"

    def test_nested_relative(self):
        result = resolve_relative_import("./sub/Detail", "src/pages/Product.jsx")
        assert result == "src/pages/sub/Detail"

    def test_double_parent(self):
        result = resolve_relative_import("../../utils/format", "src/components/deep/Item.jsx")
        assert result == "src/utils/format"

    def test_root_level(self):
        result = resolve_relative_import("./App", "index.jsx")
        assert result == "App"


class TestExpandExtensions:
    def test_basic_expansion(self):
        candidates = expand_extensions("src/components/Cart")
        assert "src/components/Cart.jsx" in candidates
        assert "src/components/Cart.js" in candidates
        assert "src/components/Cart.tsx" in candidates
        assert "src/components/Cart.ts" in candidates
        assert "src/components/Cart/index.jsx" in candidates
        assert "src/components/Cart/index.js" in candidates
        assert "src/components/Cart/index.tsx" in candidates
        assert "src/components/Cart/index.ts" in candidates
        assert len(candidates) == 8


class TestExtractRenderedComponent:
    def test_react18_createroot(self):
        code = """
import { createRoot } from 'react-dom/client';
import App from './App';

const root = createRoot(document.getElementById('root'));
root.render(<App />);
"""
        assert _extract_rendered_component(code) == "App"

    def test_react16_render(self):
        code = """
import ReactDOM from 'react-dom';
import App from './App';

ReactDOM.render(<App />, document.getElementById('root'));
"""
        assert _extract_rendered_component(code) == "App"

    def test_with_strictmode_wrapper(self):
        code = """
import ReactDOM from 'react-dom';
import App from './App';

ReactDOM.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
  document.getElementById('root')
);
"""
        assert _extract_rendered_component(code) == "App"

    def test_bare_render_import(self):
        """`import { render } from 'react-dom'` — todoist's entrypoint."""
        code = """
import React from 'react';
import { render } from 'react-dom';
import { App } from './App';
import './App.scss';

render(<App />, document.getElementById('root'));
"""
        assert _extract_rendered_component(code) == "App"

    def test_bare_hydrate_import(self):
        code = """
import { hydrate } from 'react-dom';
import App from './App';

hydrate(<App />, document.getElementById('root'));
"""
        assert _extract_rendered_component(code) == "App"

    def test_identifier_ending_in_render_is_not_a_render_call(self):
        code = """
const rerender = (el) => el;
rerender(<Widget />);
"""
        assert _extract_rendered_component(code) is None

    def test_no_render_call(self):
        code = """
function MyComponent() {
  return <div>Hello</div>;
}
export default MyComponent;
"""
        assert _extract_rendered_component(code) is None

    def test_with_provider_wrapper(self):
        code = """
import { createRoot } from 'react-dom/client';
import { Provider } from 'react-redux';
import App from './App';
import store from './store';

const root = createRoot(document.getElementById('root'));
root.render(
  <Provider store={store}>
    <App />
  </Provider>
);
"""
        assert _extract_rendered_component(code) == "App"


class TestFindEntrypoint:
    """Entrypoint search: only extracted files count, and a failed candidate is not final."""

    RENDER = "import { render } from 'react-dom';\nrender(<App />, document.getElementById('root'));\n"

    def _repo(self, tmp_path, files: dict[str, str], main: str | None = None):
        import json as _json
        (tmp_path / "package.json").write_text(_json.dumps({"main": main} if main else {}))
        for rel, body in files.items():
            (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / rel).write_text(body)
        return tmp_path

    def test_excluded_main_is_skipped(self, tmp_path):
        """takenote: `main` is the excluded Express server; the client entry is elsewhere."""
        from src.extraction.cross_file import find_entrypoint
        repo = self._repo(tmp_path, {
            "src/server/index.ts": "import express from 'express';\n",
            "src/client/index.tsx": self.RENDER,
            "src/client/App.tsx": "export const App = () => null;\n",
        }, main="src/server/index.ts")
        manifest = ["src/client/index.tsx", "src/client/App.tsx"]
        assert find_entrypoint(repo, manifest) == ("src/client/index.tsx", "App")

    def test_conventional_path_still_first(self, tmp_path):
        from src.extraction.cross_file import find_entrypoint
        repo = self._repo(tmp_path, {
            "src/index.js": self.RENDER,
            "src/other/index.js": self.RENDER.replace("App", "Other"),
        })
        assert find_entrypoint(repo, ["src/index.js", "src/other/index.js"]) == ("src/index.js", "App")

    def test_candidate_without_render_falls_through(self, tmp_path):
        from src.extraction.cross_file import find_entrypoint
        repo = self._repo(tmp_path, {
            "src/index.js": "export * from './lib';\n",
            "src/app/main.jsx": self.RENDER,
        })
        assert find_entrypoint(repo, ["src/index.js", "src/app/main.jsx"]) == ("src/app/main.jsx", "App")

    def test_no_render_anywhere(self, tmp_path):
        from src.extraction.cross_file import find_entrypoint
        repo = self._repo(tmp_path, {"src/lib.js": "export const x = 1;\n"})
        assert find_entrypoint(repo, ["src/lib.js"]) is None

    def test_without_manifest_keeps_old_behaviour(self, tmp_path):
        from src.extraction.cross_file import find_entrypoint
        repo = self._repo(tmp_path, {"src/index.jsx": self.RENDER})
        assert find_entrypoint(repo) == ("src/index.jsx", "App")
