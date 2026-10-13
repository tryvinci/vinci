#!/usr/bin/env python3
"""Write reproducible studio-bundle.lock.json (npm production tree fingerprint)."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


def fingerprint_bundle(root: Path) -> dict:
    files: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel.startswith("node_modules/.cache"):
            continue
        if "/node_modules/" in rel or rel.startswith("node_modules/"):
            files.append(rel)
    h = hashlib.sha256()
    for rel in files:
        h.update(rel.encode())
        h.update(path.read_bytes())
    lock_path = root / "package-lock.json"
    lock_sha = hashlib.sha256(lock_path.read_bytes()).hexdigest() if lock_path.is_file() else ""
    next_pkg = root / "node_modules" / "next" / "package.json"
    next_ver = ""
    if next_pkg.is_file():
        next_ver = json.loads(next_pkg.read_text(encoding="utf-8")).get("version", "")
    return {
        "schema": 1,
        "next_version": next_ver,
        "package_lock_sha256": lock_sha,
        "node_modules_file_count": len(files),
        "node_modules_tree_sha256": h.hexdigest(),
    }


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: write-studio-bundle-lock.py <bundle-dir>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1])
    data = fingerprint_bundle(root)
    out = root / "studio-bundle.lock.json"
    out.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
