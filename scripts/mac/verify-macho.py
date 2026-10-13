#!/usr/bin/env python3
"""Fail if Mach-O binaries link outside Apple system libs or @rpath/@loader_path."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ALLOWED_PREFIXES = (
    "/usr/lib/",
    "/System/Library/",
    "/Library/Apple/",
    "@rpath/",
    "@loader_path/",
    "@executable_path/",
)


def is_macho(path: Path) -> bool:
    try:
        out = subprocess.check_output(["file", "-b", str(path)], text=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    return "Mach-O" in out


def otool_deps(path: Path) -> list[str]:
    out = subprocess.check_output(["otool", "-L", str(path)], text=True, errors="replace")
    lines = out.splitlines()[1:]
    deps: list[str] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        dep = line.split(" (compat")[0].strip()
        deps.append(dep)
    return deps


def forbidden_dep(dep: str) -> bool:
    if dep.startswith("/opt/homebrew") or dep.startswith("/usr/local/"):
        return True
    if dep.startswith("/"):
        return not any(dep.startswith(prefix) for prefix in ALLOWED_PREFIXES if prefix.startswith("/"))
    return not dep.startswith("@")


def audit_tree(root: Path) -> int:
    bad = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix in {".png", ".jpg", ".json", ".js", ".mjs", ".cjs", ".txt", ".md", ".html"}:
            continue
        if not is_macho(path):
            continue
        for dep in otool_deps(path):
            if forbidden_dep(dep):
                rel = path.relative_to(root)
                print(f"forbidden link {rel}: {dep}", file=sys.stderr)
                bad += 1
    if bad:
        return 1
    print(f"macho audit ok: {root}")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: verify-macho.py <path>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1])
    if not root.exists():
        print(f"missing: {root}", file=sys.stderr)
        return 2
    if sys.platform != "darwin":
        print("verify-macho.py: skipped (not macOS)")
        return 0
    return audit_tree(root)


if __name__ == "__main__":
    raise SystemExit(main())
