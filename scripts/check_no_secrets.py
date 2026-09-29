#!/usr/bin/env python3
"""Fail CI if live-looking secrets appear in the OSS tree.

Secret *names* (WAVESPEED_API_KEY, GEMINI_API_KEY, …) are allowed.
Values belong in keychain / env / config refs, never in git.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Fixture strings used to prove redaction. They are not live keys.
ALLOWED_VALUES = (
    "sk-conformance-never-log-me",
    "sk-never-spend",
    "supersecret-demo-key",
    "mcp-secret-value",
)

LEAK_RES = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ghp_[A-Za-z0-9]{36}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----"),
    re.compile(r"sk-live-[A-Za-z0-9]{16,}"),
    re.compile(r"sk-proj-[A-Za-z0-9_-]{20,}"),
    re.compile(r"(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{20,}"),
)

SKIP_PARTS = {".git", "node_modules", ".venv", "venv", ".mypy_cache", ".ruff_cache", "dist"}


def _scrubbed(text: str) -> str:
    out = text
    for value in ALLOWED_VALUES:
        out = out.replace(value, "")
    return out


def findings_in_text(text: str) -> list[str]:
    blob = _scrubbed(text)
    hits: list[str] = []
    for cre in LEAK_RES:
        if cre.search(blob):
            hits.append(cre.pattern)
    return hits


def iter_files(root: Path = ROOT) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_PARTS for part in path.parts):
            continue
        files.append(path)
    return files


def scan(root: Path = ROOT) -> list[str]:
    failures: list[str] = []
    for path in iter_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rel = path.relative_to(root)
        for pattern in findings_in_text(text):
            failures.append(f"{rel}: possible secret ({pattern})")
    return failures


def main() -> int:
    failures = scan()
    if failures:
        print("secret scan failed:")
        for line in failures:
            print(f"  {line}")
        return 1
    print("secret scan clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
