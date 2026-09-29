#!/usr/bin/env python3
"""Fail CI if proprietary or AGPL markers appear in the OSS tree."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Filename matches are always banned (except this scanner and legal/docs notes).
BANNED_FILE_RES = (
    re.compile(r"vinci_ai_service", re.I),
    re.compile(r"dodo_payments", re.I),
)

# Content matches. Docs may mention the words as exclusions.
ALLOWED_DOC_PREFIXES = (
    ROOT / "legal",
    ROOT / "docs",
    ROOT / "NAMESPACE.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "SECURITY.md",
    ROOT / "README.md",
    ROOT / "scripts" / "check_no_proprietary.py",
)

CONTENT_BANS = (
    (re.compile(r"\bClerk\b"), "Clerk tenancy belongs in Vinci Platform"),
    (re.compile(r"\bDodo\b"), "Dodo/credits belong in Vinci Platform"),
    (re.compile(r"mongodb(\+srv)?:\/\/", re.I), "Mongo URLs must not ship in OSS"),
    (re.compile(r"AGPL-3\.0"), "AGPL license identifier in non-doc file"),
)


def _is_allowed_doc(path: Path) -> bool:
    resolved = path.resolve()
    for prefix in ALLOWED_DOC_PREFIXES:
        try:
            resolved.relative_to(prefix.resolve())
            return True
        except ValueError:
            continue
    return False


def _iter_files() -> list[Path]:
    skip_parts = {".git", "node_modules", ".venv", "venv", ".mypy_cache", ".ruff_cache", "dist"}
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in skip_parts for part in path.parts):
            continue
        files.append(path)
    return files


def main() -> int:
    failures: list[str] = []
    for path in _iter_files():
        rel = path.relative_to(ROOT)
        for cre in BANNED_FILE_RES:
            if cre.search(path.name):
                failures.append(f"{rel}: banned filename ({cre.pattern})")
        if _is_allowed_doc(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for cre, why in CONTENT_BANS:
            if cre.search(text):
                failures.append(f"{rel}: {why} ({cre.pattern})")
    if failures:
        print("proprietary/AGPL scan failed:")
        for line in failures:
            print(f"  {line}")
        return 1
    print("proprietary/AGPL scan clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
