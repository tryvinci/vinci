#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def is_macho(path: Path) -> bool:
    try:
        out = subprocess.check_output(["file", "-b", str(path)], text=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    return "Mach-O" in out


def main() -> int:
    root = Path(sys.argv[1])
    for path in sorted(root.rglob("*")):
        if path.is_file() and is_macho(path):
            print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
