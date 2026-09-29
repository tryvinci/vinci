#!/usr/bin/env python3
"""Validate first-party skill manifests."""

from __future__ import annotations

import sys
from pathlib import Path

from vinci_skills import validate_skill_dir

ROOT = Path(__file__).resolve().parents[1] / "skills"


def main() -> int:
    errors: list[str] = []
    found = 0
    for path in sorted(ROOT.iterdir()):
        if not path.is_dir() or not (path / "vinci.yaml").is_file():
            continue
        found += 1
        for err in validate_skill_dir(path):
            errors.append(f"{path.name}: {err}")
    if found < 3:
        errors.append(f"expected at least 3 skills, found {found}")
    if errors:
        print("skill validation failed:")
        for line in errors:
            print(f"  {line}")
        return 1
    print(f"skill validation ok ({found} skills)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
