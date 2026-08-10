"""Tests for programmatic extraction functions."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from src.extraction.programmatic import (
    extract_project,
    extract_files,
    extract_libraries,
    classify_category,
)


class TestClassifyCategory:
    def test_exact_matches(self):
        assert classify_category("react") == "framework"
        assert classify_category("react-dom") == "framework"
        assert classify_category("redux") == "state-management"
        assert classify_category("react-router-dom") == "routing"
        assert classify_category("axios") == "utility"
        assert classify_category("jest") == "testing"
        assert classify_category("webpack") == "build-tool"
        assert classify_category("styled-components") == "ui-library"

    def test_prefix_matches(self):
        assert classify_category("@mui/material") == "ui-library"
        assert classify_category("@radix-ui/react-dialog") == "ui-library"
        assert classify_category("@testing-library/react") == "testing"
        assert classify_category("@babel/core") == "build-tool"

    def test_unknown_packages(self):
        assert classify_category("my-custom-lib") == "other"
        assert classify_category("@my-scope/utils") == "other"


class TestExtractProject:
    def test_basic_project(self, tmp_path):
        pkg = {
            "name": "my-app",
            "description": "A test React app",
            "dependencies": {"react": "^18.0.0"},
        }
        (tmp_path / "package.json").write_text(json.dumps(pkg))

        result = extract_project(tmp_path)
        assert result is not None
        assert result["name"] == "my-app"
        assert result["description"] == "A test React app"
        assert result["projectId"] is not None

    def test_missing_package_json(self, tmp_path):
        result = extract_project(tmp_path)
        assert result is None

    def test_no_name_fallback(self, tmp_path):
        pkg = {"version": "1.0.0"}
        (tmp_path / "package.json").write_text(json.dumps(pkg))

        result = extract_project(tmp_path)
        assert result is not None
        assert result["name"] == tmp_path.name


class TestExtractFiles:
    def test_includes_jsx_files(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "App.jsx").write_text("export default function App() {}")
        (src / "index.js").write_text("import App from './App';")

        files = extract_files(tmp_path)
        paths = [f["filePath"] for f in files]
        assert "src/App.jsx" in paths
        assert "src/index.js" in paths

    def test_excludes_node_modules(self, tmp_path):
        nm = tmp_path / "node_modules" / "react"
        nm.mkdir(parents=True)
        (nm / "index.js").write_text("module.exports = {};")

        src = tmp_path / "src"
        src.mkdir()
        (src / "App.jsx").write_text("")

        files = extract_files(tmp_path)
        paths = [f["filePath"] for f in files]
        assert not any("node_modules" in p for p in paths)

    def test_excludes_test_files(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "App.jsx").write_text("")
        (src / "App.test.jsx").write_text("")
        (src / "App.spec.js").write_text("")

        files = extract_files(tmp_path)
        paths = [f["filePath"] for f in files]
        assert "src/App.jsx" in paths
        assert "src/App.test.jsx" not in paths
        assert "src/App.spec.js" not in paths

    def test_excludes_config_files(self, tmp_path):
        (tmp_path / "vite.config.js").write_text("")
        (tmp_path / "babel.config.js").write_text("")

        src = tmp_path / "src"
        src.mkdir()
        (src / "App.jsx").write_text("")

        files = extract_files(tmp_path)
        paths = [f["filePath"] for f in files]
        assert "vite.config.js" not in paths
        assert "babel.config.js" not in paths

    def test_excludes_type_definitions(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "App.tsx").write_text("")
        (src / "types.d.ts").write_text("")

        files = extract_files(tmp_path)
        paths = [f["filePath"] for f in files]
        assert "src/App.tsx" in paths
        assert "src/types.d.ts" not in paths

    def test_sorted_output(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "Zebra.jsx").write_text("")
        (src / "Alpha.jsx").write_text("")
        (src / "Middle.jsx").write_text("")

        files = extract_files(tmp_path)
        paths = [f["filePath"] for f in files]
        assert paths == sorted(paths)


class TestExtractFilesExcludePaths:
    def test_exclude_paths_blocks_directory(self, tmp_path):
        """src/server/index.ts is excluded but src/serverUtils.ts is NOT."""
        server = tmp_path / "src" / "server"
        server.mkdir(parents=True)
        (server / "index.ts").write_text("")

        src = tmp_path / "src"
        (src / "serverUtils.ts").write_text("")
        (src / "App.tsx").write_text("")

        files = extract_files(tmp_path, exclude_paths=["src/server"])
        paths = [f["filePath"] for f in files]

        assert "src/server/index.ts" not in paths
        assert "src/serverUtils.ts" in paths
        assert "src/App.tsx" in paths

    def test_exclude_paths_nested(self, tmp_path):
        """Files deep inside an excluded prefix are also excluded."""
        deep = tmp_path / "src" / "server" / "handlers"
        deep.mkdir(parents=True)
        (deep / "auth.ts").write_text("")

        src = tmp_path / "src"
        (src / "App.tsx").write_text("")

        files = extract_files(tmp_path, exclude_paths=["src/server"])
        paths = [f["filePath"] for f in files]

        assert "src/server/handlers/auth.ts" not in paths
        assert "src/App.tsx" in paths

    def test_no_exclude_paths_is_backward_compatible(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "App.jsx").write_text("")

        files_default = extract_files(tmp_path)
        files_empty = extract_files(tmp_path, exclude_paths=[])
        assert files_default == files_empty


class TestExtractLibraries:
    def test_basic_dependencies(self, tmp_path):
        pkg = {
            "dependencies": {
                "react": "^18.2.0",
                "react-dom": "^18.2.0",
                "axios": "^1.6.0",
            },
            "devDependencies": {
                "jest": "^29.0.0",
            },
        }
        (tmp_path / "package.json").write_text(json.dumps(pkg))

        libraries = extract_libraries(tmp_path)
        lib_names = [lib["name"] for lib, _ in libraries]
        assert "react" in lib_names
        assert "axios" in lib_names
        assert "jest" in lib_names

    def test_dependency_types(self, tmp_path):
        pkg = {
            "dependencies": {"react": "^18.0.0"},
            "devDependencies": {"jest": "^29.0.0"},
        }
        (tmp_path / "package.json").write_text(json.dumps(pkg))

        libraries = extract_libraries(tmp_path)
        lib_map = {lib["name"]: dt for lib, dt in libraries}
        assert lib_map["react"] == "production"
        assert lib_map["jest"] == "development"

    def test_missing_package_json(self, tmp_path):
        libraries = extract_libraries(tmp_path)
        assert libraries == []
