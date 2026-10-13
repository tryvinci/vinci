#!/usr/bin/env python3
"""Build PyPI notice list from hashed lock + local manifest (versions from lock only)."""

from __future__ import annotations

import argparse
import email
import json
import re
import subprocess
import sys
import tempfile
import zipfile
from importlib import metadata as md
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
from notice_graph import local_paths_from_manifest, normalize_name, pypi_versions_from_lock  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
LICENSE_UNKNOWN = re.compile(r"^(UNKNOWN|unknown|)$")


def license_from_classifiers(classifiers: list[str]) -> str:
    for c in classifiers:
        if c.startswith("License ::"):
            return c.split("::", 1)[-1].strip()
    return ""


def _license_from_metadata_text(text: str) -> str:
    msg = email.message_from_string(text)
    lic = (msg.get("License-Expression") or msg.get("License") or "").strip()
    if lic and not LICENSE_UNKNOWN.match(lic):
        return lic
    return license_from_classifiers(msg.get_all("Classifier", []) or [])


def license_from_downloaded_dist(name: str, version: str) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        td = Path(tmp)
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "download", "--no-deps", f"{name}=={version}", "-d", str(td)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            print(f"pip download failed for {name}=={version}: {proc.stderr}", file=sys.stderr)
            return ""
        for path in td.iterdir():
            if path.suffix == ".whl":
                with zipfile.ZipFile(path) as zf:
                    meta_name = next(n for n in zf.namelist() if n.endswith("METADATA"))
                    return _license_from_metadata_text(zf.read(meta_name).decode("utf-8", errors="replace"))
            if path.suffix == ".gz" and path.name.endswith(".tar.gz"):
                import tarfile

                with tarfile.open(path) as tar:
                    member = next(
                        m for m in tar.getmembers() if m.name.endswith("PKG-INFO") or m.name.endswith("METADATA")
                    )
                    text = tar.extractfile(member).read().decode("utf-8", errors="replace")
                    return _license_from_metadata_text(text)
    return ""


def license_for_pinned(name: str, version: str) -> str:
    key = normalize_name(name)
    try:
        dists = list(md.distributions())
    except Exception:
        dists = []
    for dist in dists:
        if normalize_name(dist.metadata.get("Name", "")) != key:
            continue
        try:
            if dist.version != version:
                continue
        except Exception:
            continue
        lic = dist.metadata.get("License-Expression") or dist.metadata.get("License") or ""
        lic = str(lic).strip()
        if lic and not LICENSE_UNKNOWN.match(lic):
            return lic
    return license_from_downloaded_dist(name, version)


def display_name_for_normalized(norm: str, lock_path: Path) -> str:
    for line in lock_path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==", line.strip())
        if m and normalize_name(m.group(1)) == norm:
            return m.group(1)
    return norm


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", default=str(ROOT / "scripts/mac/python-bundle-runtime.lock.txt"))
    parser.add_argument("--manifest", default=str(ROOT / "scripts/mac/python-bundle-local.manifest.json"))
    parser.add_argument("--out", default=str(ROOT / "scripts/mac/python-bundle-notices.json"))
    args = parser.parse_args()
    lock = Path(args.lock)
    manifest = Path(args.manifest)
    out = Path(args.out)
    if not lock.is_file() or not manifest.is_file():
        print("missing lock or manifest", file=sys.stderr)
        return 1
    versions = pypi_versions_from_lock(lock)
    if len(versions) < 5:
        print("lock has too few pypi packages", file=sys.stderr)
        return 1
    pypi = []
    for norm in sorted(versions):
        version = versions[norm]
        display = display_name_for_normalized(norm, lock)
        lic = license_for_pinned(display, version)
        if not lic or LICENSE_UNKNOWN.match(lic):
            print(f"missing license for {display}=={version}", file=sys.stderr)
            return 1
        pypi.append(
            {
                "name": display,
                "version": version,
                "license": lic,
                "source": "pypi",
            }
        )
    local_paths = local_paths_from_manifest(manifest)
    local = []
    for rel, sha in local_paths.items():
        if not sha or len(sha) != 64:
            print(f"bad manifest digest for {rel}", file=sys.stderr)
            return 1
        local.append(
            {
                "name": rel,
                "version": "workspace",
                "license": "MIT",
                "source": "monorepo",
                "sha256": sha,
            }
        )
    payload = {"schema": 2, "pypi": pypi, "local": local, "lock_sha256": _lock_digest(lock)}
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(pypi)} pypi, {len(local)} local)")
    return 0


def _lock_digest(lock: Path) -> str:
    import hashlib

    return hashlib.sha256(lock.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
