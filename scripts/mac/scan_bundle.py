#!/usr/bin/env python3
"""Fail if a Mac bundle contains banned paths or license markers."""

from __future__ import annotations

import re
import sys
from pathlib import Path

# __editable__: an editable install points at the build checkout (COREPRODUC-520).
BANNED_NAME = re.compile(r"vinci[-_]?clips|\.env$|id_rsa|__editable__", re.I)
BANNED_CONTENT = (
    re.compile(r"AGPL-3\.0"),
    # Only URLs that carry credentials (user:pass@); pydantic documents bare Mongo host URLs.
    re.compile(r"mongodb(\+srv)?:\/\/[^\s/@:]+:[^\s/@]+@", re.I),
    re.compile(r"\bClerk\b"),
)
# SPDX license-ID tables list every license name (AGPL included); they are data, not AGPL code.
LICENSE_ID_TABLES = ("packaging/licenses/_spdx.py",)


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: scan_bundle.py <Vinci Studio.app>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1])
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2
    bad = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if BANNED_NAME.search(path.name):
            print(f"banned name: {rel}")
            bad += 1
            continue
        if path.suffix in {".png", ".jpg", ".mp4", ".zip", ".gz", ".so", ".dylib"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pat in BANNED_CONTENT:
            if pat.pattern == r"AGPL-3\.0" and rel.as_posix().endswith(LICENSE_ID_TABLES):
                continue
            if pat.search(text):
                print(f"banned content in {rel}: {pat.pattern}")
                bad += 1
                break
    if bad:
        return 1
    print(f"scan ok: {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
