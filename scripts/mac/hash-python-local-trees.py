#!/usr/bin/env python3
"""Deterministic sha256 over local -e package trees for Mac bundle manifest."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
from notice_graph import local_editable_paths_from_in  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "scripts/mac/python-bundle-local.manifest.json"
SKIP = {".pyc", "__pycache__", ".pytest_cache", ".ruff_cache", ".egg-info"}


def tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if any(part in SKIP for part in path.parts):
            continue
        digest.update(rel.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def main() -> int:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT
    entries: dict[str, dict[str, str]] = {}
    for rel in local_editable_paths_from_in():
        root = (ROOT / rel).resolve()
        if not root.is_dir():
            print(f"missing local package tree: {root}", file=sys.stderr)
            return 1
        entries[rel] = {"sha256": tree_sha256(root)}
    payload = {"schema": 1, "packages": entries}
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out_path} ({len(entries)} trees)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
