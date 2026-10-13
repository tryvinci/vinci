#!/usr/bin/env python3
"""Strip editable (-e) stanzas from pip-compile output; keep hashed PyPI pins only."""

from __future__ import annotations

import re
import sys
from pathlib import Path

PKG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*==")
WARNING = re.compile(r"^# WARNING: pip install will require")


def main() -> int:
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    out: list[str] = [
        "#",
        "# Hashed PyPI runtime lock (editable Vinci trees installed separately).",
        "# Regenerate: scripts/mac/generate-python-bundle-lock.sh",
        "#",
    ]
    skip = False
    for line in src.read_text(encoding="utf-8").splitlines():
        if WARNING.match(line.strip()):
            skip = True
            continue
        if line.startswith("-e "):
            skip = True
            continue
        if skip:
            if line.startswith("#") or not line.strip():
                continue
            if PKG.match(line):
                skip = False
            else:
                continue
        if line.startswith("# WARNING: The following packages are considered to be unsafe"):
            skip = False
        if skip:
            continue
        out.append(line)
    dst.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    print(f"wrote {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main() if len(sys.argv) == 3 else main())
