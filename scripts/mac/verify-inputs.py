#!/usr/bin/env python3
"""Fail closed unless deps.lock.json has trusted upstream digests and cache files match."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOCK = Path(__file__).resolve().parent / "deps.lock.json"
CACHE = ROOT / ".mac-bundle-cache"
PLACEHOLDER = re.compile(r"PLACEHOLDER", re.I)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_lock(lock_path: Path) -> dict:
    data = json.loads(lock_path.read_text(encoding="utf-8"))
    return data


def check_digest_field(name: str, value: str) -> None:
    if not value or PLACEHOLDER.search(value):
        raise SystemExit(f"{name}: missing or placeholder digest in lock file")
    if len(value) != 64 or not re.fullmatch(r"[0-9a-f]+", value):
        raise SystemExit(f"{name}: digest must be 64-char lowercase hex")


def verify_lock_structure(data: dict) -> None:
    for key in ("python_build_standalone", "node", "ffmpeg_source"):
        if key not in data:
            raise SystemExit(f"deps.lock missing key: {key}")
    check_digest_field("python", data["python_build_standalone"]["sha256"])
    check_digest_field("node", data["node"]["sha256"])
    check_digest_field("ffmpeg_source", data["ffmpeg_source"]["sha256"])


def cache_paths(data: dict) -> dict[str, Path]:
    py_name = data["python_build_standalone"]["url"].rstrip("/").split("/")[-1]
    node_name = data["node"]["url"].rstrip("/").split("/")[-1]
    ff_name = data["ffmpeg_source"]["url"].rstrip("/").split("/")[-1]
    return {
        "python": CACHE / py_name,
        "node": CACHE / node_name,
        "ffmpeg_source": CACHE / ff_name,
        "ffmpeg": CACHE / "ffmpeg-arm64" / "bin" / "ffmpeg",
        "ffprobe": CACHE / "ffmpeg-arm64" / "bin" / "ffprobe",
    }


def verify_cache(data: dict, require_ffmpeg_bin: bool) -> None:
    paths = cache_paths(data)
    expected_map = {
        "python": data["python_build_standalone"]["sha256"],
        "node": data["node"]["sha256"],
        "ffmpeg_source": data["ffmpeg_source"]["sha256"],
    }
    for label in ("python", "node", "ffmpeg_source"):
        path = paths[label]
        if not path.is_file():
            raise SystemExit(f"cache missing {label}: {path} (run scripts/mac/fetch-deps.sh)")
        actual = sha256_file(path)
        if actual != expected_map[label]:
            raise SystemExit(f"cache digest mismatch for {label}: {path}")


    if require_ffmpeg_bin:
        for label in ("ffmpeg", "ffprobe"):
            path = paths[label]
            if not path.is_file():
                raise SystemExit(
                    f"cache missing built {label}: {path} "
                    "(run scripts/mac/build-ffmpeg.sh on macOS arm64)"
                )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", default=str(DEFAULT_LOCK), help="Path to deps.lock.json")
    parser.add_argument(
        "--require-cache",
        action="store_true",
        help="Require .mac-bundle-cache artifacts with matching digests",
    )
    parser.add_argument(
        "--require-ffmpeg-bin",
        action="store_true",
        help="Require built ffmpeg/ffprobe under .mac-bundle-cache/ffmpeg-arm64/bin",
    )
    args = parser.parse_args()
    lock_path = Path(args.lock)
    if not lock_path.is_file():
        print(f"lock file not found: {lock_path}", file=sys.stderr)
        return 1
    data = load_lock(lock_path)
    verify_lock_structure(data)
    if args.require_cache:
        verify_cache(data, require_ffmpeg_bin=args.require_ffmpeg_bin)
    print(f"verify-inputs ok ({lock_path.name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
