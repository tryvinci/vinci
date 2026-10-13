#!/usr/bin/env python3
"""Dereference symlinks and prune top-level devDependencies from studio bundle."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

TOP_LEVEL_DEV = (
    "typescript",
    "eslint",
    "prettier",
    "@types",
)


def materialize_symlinks(root: Path) -> int:
    count = 0
    for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if not path.is_symlink():
            continue
        target = Path(os.path.realpath(path))
        path.unlink()
        if target.is_dir():
            shutil.copytree(target, path, symlinks=True)
        elif target.is_file():
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, path)
        count += 1
    return count


def prune_dev(root: Path) -> int:
    nm = root / "node_modules"
    if not nm.is_dir():
        return 0
    count = 0
    for name in TOP_LEVEL_DEV:
        path = nm / name
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
            count += 1
        elif path.exists():
            path.unlink(missing_ok=True)
            count += 1
    return count


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: prune-studio-bundle.py <studio-bundle>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1])
    materialized = materialize_symlinks(root)
    dev = prune_dev(root)
    remaining = [p for p in root.rglob("*") if p.is_symlink()]
    if remaining:
        for link in remaining[:10]:
            print(f"symlink remains: {link}", file=sys.stderr)
        return 1
    print(f"prune ok: materialized={materialized} dev_pruned={dev}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
