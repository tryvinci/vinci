#!/usr/bin/env python3
"""Assert Mac .app staging paths required by build-app.sh exist."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def required_inputs() -> list[Path]:
    lock = ROOT / "scripts/mac/deps.lock.json"
    import json

    node_tar = json.loads(lock.read_text(encoding="utf-8"))["node"]["url"].split("/")[-1]
    cache = ROOT / ".mac-bundle-cache"
    return [
        cache / "python-prefix/bin/python3",
        cache / "ffmpeg-arm64/bin/ffmpeg",
        cache / "ffmpeg-arm64/bin/ffprobe",
        ROOT / "dist/studio-bundle/server.js",
        ROOT / "dist/studio-bundle/node_modules/next/package.json",
        ROOT / "dist/studio-bundle/studio-launcher.cjs",
        ROOT / "apps/mac/Info.plist",
        ROOT / "apps/mac/VinciStudio.swift",
        ROOT / "apps/mac/SmokeRunner.swift",
        cache / node_tar,
        ROOT / "legal/THIRD_PARTY_NOTICES.md",
        ROOT / "legal/provenance.json",
    ]


def required_app_paths(app: Path) -> list[Path]:
    return [
        app / "Contents/Info.plist",
        app / "Contents/MacOS/VinciStudio",
        app / "Contents/Resources/runtime/bin/python3",
        app / "Contents/Resources/studio/server.js",
        app / "Contents/Resources/studio/node",
        app / "Contents/Resources/bin/ffmpeg",
        app / "Contents/Resources/bin/ffprobe",
        app / "Contents/Resources/legal/THIRD_PARTY_NOTICES.md",
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prebuild", action="store_true", help="Check inputs before swift compile")
    parser.add_argument("--app", type=Path, help="Check staged .app after build")
    args = parser.parse_args()
    missing: list[str] = []
    paths: list[Path] = []
    if args.prebuild:
        paths.extend(required_inputs())
    if args.app:
        paths.extend(required_app_paths(args.app))
    if not paths:
        parser.print_help()
        return 2
    for path in paths:
        if not path.exists():
            missing.append(str(path.relative_to(ROOT) if path.is_absolute() else path))
    if missing:
        print("packaging paths missing:", file=sys.stderr)
        for item in missing:
            print(f"  - {item}", file=sys.stderr)
        return 1
    print(f"packaging paths ok ({len(paths)} checked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
