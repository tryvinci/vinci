#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: verify-studio-bundle.py <bundle-dir>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1])
    required = [
        root / "server.js",
        root / ".next" / "static",
    ]
    for path in required:
        if not path.exists():
            print(f"missing bundle path: {path}", file=sys.stderr)
            return 1
    nm = root / "node_modules" / "next"
    if not nm.is_dir():
        print(f"missing traced next module: {nm}", file=sys.stderr)
        return 1
    lock = root / "studio-bundle.lock.json"
    if not lock.is_file():
        print(f"missing studio bundle lock: {lock}", file=sys.stderr)
        return 1
    print(f"studio bundle verify ok: {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
