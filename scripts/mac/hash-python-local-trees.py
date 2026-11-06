#!/usr/bin/env python3
"""Hash the local -e package trees at build time for Mac bundle provenance.

The committed manifest lists tree paths only. The digests go to a gitignored file, so
a source edit does not make a committed file stale (COREPRODUC-508).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
from notice_graph import LOCAL_DIGESTS, local_paths_from_manifest  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "scripts/mac/python-bundle-local.manifest.json"
SKIP = {".pyc", "__pycache__", ".pytest_cache", ".ruff_cache", ".egg-info"}


def tree_sha256(root: Path) -> str:
    """Return a deterministic sha256 over the relative paths and bytes of a tree.

    Args:
        root: Package tree to hash. Caches and ``*.egg-info`` are skipped.

    Returns:
        Hex sha256 digest.
    """
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if any(part in SKIP or part.endswith(".egg-info") for part in path.parts):
            continue
        digest.update(rel.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=LOCAL_DIGESTS, help="digests JSON to write")
    args = parser.parse_args()
    try:
        paths = local_paths_from_manifest(MANIFEST)
    except ValueError as exc:
        print(f"local manifest invalid: {exc}", file=sys.stderr)
        return 1
    digests = {rel: tree_sha256(ROOT / rel) for rel in paths}
    for rel, sha in digests.items():
        print(f"  {rel}: {sha[:12]}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema": 1, "packages": digests}
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {args.out} ({len(digests)} trees)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
