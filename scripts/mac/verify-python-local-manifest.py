#!/usr/bin/env python3
"""Verify committed local package tree digests match workspace and requirements.in."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
from notice_graph import local_editable_paths_from_in, local_paths_from_manifest  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "scripts/mac/python-bundle-local.manifest.json"
HASH_SCRIPT = ROOT / "scripts/mac/hash-python-local-trees.py"


def main() -> int:
    manifest_path = Path(sys.argv[1]) if len(sys.argv) > 1 else MANIFEST
    if not manifest_path.is_file():
        print(f"missing manifest: {manifest_path}", file=sys.stderr)
        return 1
    raw = manifest_path.read_text(encoding="utf-8")
    if "PLACEHOLDER" in raw:
        print("manifest contains PLACEHOLDER", file=sys.stderr)
        return 1
    try:
        expected_paths = local_paths_from_manifest(manifest_path)
    except ValueError as exc:
        print(f"manifest graph invalid: {exc}", file=sys.stderr)
        return 1
    required = local_editable_paths_from_in()
    if len(expected_paths) != len(required):
        print(
            f"manifest count {len(expected_paths)} != requirements.in {len(required)}",
            file=sys.stderr,
        )
        return 1

    spec = importlib.util.spec_from_file_location("hash_local", HASH_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    for rel, digest in expected_paths.items():
        root = (ROOT / rel).resolve()
        if not root.is_dir():
            print(f"missing tree: {rel}", file=sys.stderr)
            return 1
        actual = mod.tree_sha256(root)
        if actual != digest:
            print(f"manifest stale for {rel}: {actual} != {digest}", file=sys.stderr)
            return 1
    print(f"local manifest ok ({len(expected_paths)} trees)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
