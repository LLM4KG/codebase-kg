"""Extraction provenance — which model, which prompts, which source revision.

The committed KG dumps previously recorded only node/relationship counts, so the
repo could not say which model or which prompt texts produced them. For a thesis
whose central method is LLM-based extraction, that is the one thing the artifact
must carry.

`prompt_set_version` is a hash over the prompt template *contents*. The LLM cache
key is `(file_content_hash, prompt_id, model)` and deliberately excludes template
text (see `src/llm/cache.py`), so a silent in-place prompt edit is invisible to the
cache. Recording the hash here does not fix that, but it does make the drift
detectable after the fact: two dumps with the same model and different
`prompt_set_version` were not built the same way.
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

PROVENANCE_FILENAME = "extraction_provenance.json"

# Repo root for locating prompts/ — src/extraction/provenance.py -> repo root
_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


def compute_prompt_set_version(prompts_dir: Path | None = None) -> str:
    """Hash the *extraction* prompt templates so template drift is detectable.

    Hashes sorted (relative filename, content) pairs, so both an edit and an
    addition/removal change the result.

    Non-recursive by design. The Stage 2 and Stage 4 templates sit at the top level
    of `prompts/`; `prompts/generation/` holds Phase 2 code-generation templates
    that play no part in building the KG. A recursive walk swept those in, so
    editing `format_a.jinja2` changed the recorded extraction fingerprint of graphs
    it never touched — turning the drift signal into a false positive during
    ordinary Phase 2 work. (Retrieval's own prompts live under
    `src/retrieval/prompts/` and were never in scope.)
    """
    directory = prompts_dir or _PROMPTS_DIR
    if not directory.exists():
        return "unknown"

    digest = hashlib.sha256()
    for path in sorted(directory.glob("*.jinja2")):
        digest.update(path.name.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:12]


def get_repo_revision(repo_root: Path) -> dict:
    """Return the source revision the KG was extracted from.

    Without this, "which source produced this graph" is unanswerable — and it is
    the precondition for trusting a content-hash-keyed LLM cache across sessions.
    """
    def _git(*args: str) -> str | None:
        try:
            out = subprocess.run(
                ["git", "-C", str(repo_root), *args],
                capture_output=True, text=True, timeout=10,
            )
            return out.stdout.strip() if out.returncode == 0 else None
        except (OSError, subprocess.SubprocessError) as exc:
            logger.debug("git %s failed for %s: %s", args, repo_root, exc)
            return None

    sha = _git("rev-parse", "HEAD")
    if sha is None:
        return {"repo_commit_sha": None, "repo_dirty": None}

    status = _git("status", "--porcelain")
    return {
        "repo_commit_sha": sha,
        # A dirty tree means the dump does not correspond to any commit.
        "repo_dirty": bool(status) if status is not None else None,
    }


def build_provenance(
    repo_root: Path,
    project_id: str,
    model: str,
    prompt_ids: list[str],
    file_count: int,
) -> dict:
    """Assemble the provenance record for one extraction run."""
    return {
        "project_id": project_id,
        "extraction_model": model,
        "prompt_set_version": compute_prompt_set_version(),
        "prompt_ids": sorted(prompt_ids),
        "extracted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "file_count": file_count,
        **get_repo_revision(repo_root),
    }


def write_provenance(output_dir: Path, provenance: dict) -> Path:
    """Write the provenance record next to the raw extractions."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / PROVENANCE_FILENAME
    path.write_text(json.dumps(provenance, indent=2) + "\n")
    logger.info("Provenance written: %s", path)
    return path


def read_provenance(directory: Path) -> dict | None:
    """Read a provenance record, or None if this export has none.

    Returns None rather than raising: `pipeline export` must still produce a
    manifest for graphs extracted before provenance existed.
    """
    path = Path(directory) / PROVENANCE_FILENAME
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read provenance at %s: %s", path, exc)
        return None
