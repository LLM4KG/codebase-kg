"""Append embedding-cache rows from a worktree's cache into this tree's cache.

Worktree runs extend `embedding_cache/` from the same committed base (review F6).
Copying a file back would drop rows another worktree added; this appends only
rows whose key is not already present, preserving order and first-row-wins.

Usage: uv run python scripts/merge_embedding_cache.py <other>/embedding_cache
"""
import json
import sys
from pathlib import Path

src_root, dst_root = Path(sys.argv[1]), Path("embedding_cache")
for src in sorted(src_root.glob("*/*.jsonl")):
    dst = dst_root / src.relative_to(src_root)
    seen = set()
    if dst.exists():
        seen = {json.loads(line)["key"] for line in dst.open(encoding="utf-8") if line.strip()}
    new = [line for line in src.open(encoding="utf-8") if line.strip() and json.loads(line)["key"] not in seen]
    if new:
        dst.parent.mkdir(parents=True, exist_ok=True)
        with dst.open("a", encoding="utf-8") as f:
            f.writelines(line if line.endswith("\n") else line + "\n" for line in new)
    print(f"{dst}: +{len(new)} rows")
