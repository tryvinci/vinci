#!/usr/bin/env python3
"""Fail closed: hashed PyPI lock must not contain editable lines or missing hashes."""

from __future__ import annotations

import re
import sys
from pathlib import Path

PLACEHOLDER = re.compile(r"PLACEHOLDER", re.I)
PKG_LINE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==")
HASH_LINE = re.compile(r"^\s+--hash=sha256:[0-9a-f]{64}")


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent / "python-bundle-runtime.lock.txt")
    text = path.read_text(encoding="utf-8")
    if not path.is_file():
        print(f"missing lock: {path}", file=sys.stderr)
        return 1
    if PLACEHOLDER.search(text):
        print("lock contains PLACEHOLDER", file=sys.stderr)
        return 1
    pkg: str | None = None
    saw_hash = False
    packages = 0
    for line in text.splitlines():
        if line.strip().startswith("-e "):
            print(f"editable package not allowed in hashed lock: {line}", file=sys.stderr)
            return 1
        m = PKG_LINE.match(line.strip())
        if m:
            if pkg and not saw_hash:
                print(f"missing hash for {pkg}", file=sys.stderr)
                return 1
            pkg = m.group(1)
            packages += 1
            saw_hash = False
            continue
        if HASH_LINE.match(line):
            saw_hash = True
            if PLACEHOLDER.search(line):
                print(f"placeholder hash: {line}", file=sys.stderr)
                return 1
    if pkg and not saw_hash:
        print(f"missing hash for trailing package {pkg}", file=sys.stderr)
        return 1
    if packages < 5:
        print(f"lock suspiciously small: {packages} packages", file=sys.stderr)
        return 1
    print(f"python bundle lock ok ({packages} packages): {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
