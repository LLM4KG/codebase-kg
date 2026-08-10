"""Stage 1: Programmatic extraction — Project, File, Library nodes."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path

logger = logging.getLogger(__name__)

INCLUDE_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx"}

EXCLUDE_DIRS = {
    "node_modules", ".git", "dist", "build", ".next",
    "coverage", "__tests__", "__mocks__", ".cache", "public",
}

EXCLUDE_PATTERNS = [
    "*.test.*", "*.spec.*", "*.stories.*",
    "*.config.*", "*.setup.*", "*.d.ts",
    "setupTests.*", "reportWebVitals.*",
    "service-worker.*", "serviceWorker.*",
    "jest.*", "webpack.*", "vite.config.*",
    "babel.config.*", "tailwind.config.*",
    "postcss.config.*", "tsconfig.*", ".*rc.*", "seed.*",
]

# Category classification for known npm packages
CATEGORY_MAP = {
    "react": "framework", "react-dom": "framework",
    "react-native": "framework", "next": "framework",
    "gatsby": "framework", "remix": "framework",
    "@remix-run/react": "framework",
    "redux": "state-management", "react-redux": "state-management",
    "@reduxjs/toolkit": "state-management",
    "recoil": "state-management", "zustand": "state-management",
    "mobx": "state-management", "mobx-react": "state-management",
    "mobx-react-lite": "state-management",
    "jotai": "state-management", "valtio": "state-management",
    "xstate": "state-management", "@xstate/react": "state-management",
    "redux-thunk": "state-management", "redux-saga": "state-management",
    "redux-persist": "state-management",
    "react-router": "routing", "react-router-dom": "routing",
    "@reach/router": "routing", "@tanstack/react-router": "routing",
    "@mui/material": "ui-library", "@mui/icons-material": "ui-library",
    "@mui/system": "ui-library", "@chakra-ui/react": "ui-library",
    "antd": "ui-library", "@ant-design/icons": "ui-library",
    "react-bootstrap": "ui-library", "@headlessui/react": "ui-library",
    "styled-components": "ui-library",
    "@emotion/react": "ui-library", "@emotion/styled": "ui-library",
    "tailwindcss": "ui-library", "framer-motion": "ui-library",
    "react-icons": "ui-library", "react-toastify": "ui-library",
    "react-modal": "ui-library", "react-select": "ui-library",
    "react-datepicker": "ui-library", "react-tooltip": "ui-library",
    "react-leaflet": "ui-library", "recharts": "ui-library",
    "react-chartjs-2": "ui-library", "chart.js": "ui-library",
    "d3": "ui-library", "react-table": "ui-library",
    "@tanstack/react-table": "ui-library",
    "axios": "utility", "lodash": "utility",
    "date-fns": "utility", "moment": "utility", "dayjs": "utility",
    "uuid": "utility", "classnames": "utility", "clsx": "utility",
    "formik": "utility", "yup": "utility", "zod": "utility",
    "react-hook-form": "utility", "react-query": "utility",
    "@tanstack/react-query": "utility", "swr": "utility",
    "prop-types": "utility", "react-helmet": "utility",
    "react-helmet-async": "utility", "react-i18next": "utility",
    "i18next": "utility", "firebase": "utility",
    "socket.io-client": "utility", "graphql": "utility",
    "@apollo/client": "utility",
    "jest": "testing", "@testing-library/react": "testing",
    "@testing-library/jest-dom": "testing",
    "@testing-library/user-event": "testing",
    "enzyme": "testing", "cypress": "testing",
    "vitest": "testing", "react-test-renderer": "testing", "msw": "testing",
    "webpack": "build-tool", "vite": "build-tool",
    "@vitejs/plugin-react": "build-tool",
    "babel": "build-tool", "@babel/core": "build-tool",
    "@babel/preset-react": "build-tool",
    "esbuild": "build-tool", "parcel": "build-tool",
    "typescript": "build-tool", "eslint": "build-tool",
    "prettier": "build-tool", "react-scripts": "build-tool",
    "react-app-rewired": "build-tool",
}

PREFIX_CATEGORY_MAP = {
    "@radix-ui/": "ui-library",
    "@testing-library/": "testing",
    "@babel/": "build-tool",
    "@mui/": "ui-library",
    "@emotion/": "ui-library",
    "@chakra-ui/": "ui-library",
    "@ant-design/": "ui-library",
    "@tanstack/react-": "utility",
    "@remix-run/": "framework",
    "@xstate/": "state-management",
}


def extract_project(repo_root: Path) -> dict | None:
    """Extract Project node from package.json."""
    pkg_path = repo_root / "package.json"
    if not pkg_path.exists():
        logger.warning("No package.json found at %s", repo_root)
        return None

    pkg = json.loads(pkg_path.read_text())
    project_id = hashlib.sha256(str(repo_root.resolve()).encode()).hexdigest()[:12]

    return {
        "projectId": project_id,
        "name": pkg.get("name", repo_root.name),
        "description": pkg.get("description"),
        "file_path": str(repo_root.resolve()),
    }


def _matches_path_prefix(relative_path: str, prefix: str) -> bool:
    """Check if relative_path falls under prefix using directory-boundary matching."""
    return relative_path == prefix or relative_path.startswith(prefix + "/")


def extract_files(
    repo_root: Path,
    exclude_paths: list[str] | None = None,
) -> list[dict]:
    """Extract File nodes by walking the directory tree with filtering."""
    files = []
    exclude_paths = exclude_paths or []

    for file_path in sorted(repo_root.rglob("*")):
        if not file_path.is_file():
            continue

        # Check excluded directories
        parts = file_path.relative_to(repo_root).parts
        if any(part in EXCLUDE_DIRS for part in parts):
            continue

        relative = str(file_path.relative_to(repo_root)).replace("\\", "/")

        # Check project-level exclude_paths
        if exclude_paths and any(
            _matches_path_prefix(relative, prefix) for prefix in exclude_paths
        ):
            continue

        # Check extension
        if file_path.suffix not in INCLUDE_EXTENSIONS:
            continue

        # Check exclude patterns
        fname = file_path.name
        if any(fnmatch(fname, pat) for pat in EXCLUDE_PATTERNS):
            continue

        stat = file_path.stat()
        modified_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()

        files.append({
            "name": file_path.name,
            "filePath": relative,
            "modifiedAt": modified_at,
        })

    files.sort(key=lambda f: f["filePath"])
    return files


def classify_category(pkg_name: str) -> str:
    """Classify a package into a category using the lookup tables."""
    if pkg_name in CATEGORY_MAP:
        return CATEGORY_MAP[pkg_name]

    for prefix, category in PREFIX_CATEGORY_MAP.items():
        if pkg_name.startswith(prefix):
            return category

    return "other"


def extract_libraries(repo_root: Path) -> list[tuple[dict, str]]:
    """Extract Library nodes from package.json dependencies."""
    pkg_path = repo_root / "package.json"
    if not pkg_path.exists():
        logger.warning("No package.json found")
        return []

    pkg = json.loads(pkg_path.read_text())
    seen: dict[str, tuple[dict, str]] = {}

    for section in ["dependencies", "devDependencies"]:
        deps = pkg.get(section, {})
        dep_type = "production" if section == "dependencies" else "development"

        for pkg_name, version_range in deps.items():
            category = classify_category(pkg_name)
            lib_node = {
                "name": pkg_name,
                "version": version_range,
                "category": category,
            }

            if pkg_name not in seen:
                seen[pkg_name] = (lib_node, dep_type)
            elif dep_type == "production":
                seen[pkg_name] = (lib_node, dep_type)

    return list(seen.values())


def write_file_manifest(
    project_id: str,
    files: list[dict],
    output_path: Path,
) -> None:
    """Write a JSON manifest of extracted files for LLM processing."""
    manifest = {
        "projectId": project_id,
        "file_count": len(files),
        "files": [f["filePath"] for f in files],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, indent=2))
    logger.info("File manifest written: %d files -> %s", len(files), output_path)
