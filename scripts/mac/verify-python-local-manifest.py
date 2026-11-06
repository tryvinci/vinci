#!/usr/bin/env python3
"""Verify the committed local tree list equals the -e entries in requirements.in.

The list changes only when a local package is added or removed. Tree digests are
build-time output of hash-python-local-trees.py (COREPRODUC-508).
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
from notice_graph import local_paths_from_manifest  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "scripts/mac/python-bundle-local.manifest.json"


def main() -> int:
    manifest_path = Path(sys.argv[1]) if len(sys.argv) > 1 else MANIFEST
    if not manifest_path.is_file():
        print(f"missing manifest: {manifest_path}", file=sys.stderr)
        return 1
    try:
        paths = local_paths_from_manifest(manifest_path)
    except ValueError as exc:
        print(f"manifest graph invalid: {exc}", file=sys.stderr)
        return 1
    print(f"local manifest ok ({len(paths)} trees, equal to requirements.in -e entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
