#!/usr/bin/env python3
"""Parse Mac bundle notice graphs from lock files (shared by collect + verify)."""

from __future__ import annotations

import json
import re
from pathlib import Path

PKG_LINE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s\\]+)")
ROOT = Path(__file__).resolve().parents[2]
STUDIO_PKG = "apps/studio"
REQUIREMENTS_IN = ROOT / "scripts/mac/python-bundle-requirements.in"
NPM_GRAPH = ROOT / "scripts/mac/studio-bundle-npm-graph.json"


def normalize_name(name: str) -> str:
    return name.lower().replace("_", "-")


def local_editable_paths_from_in(in_path: Path | None = None) -> list[str]:
    path = in_path or REQUIREMENTS_IN
    paths: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("-e "):
            rel = line[3:].strip()
            if rel:
                paths.append(rel)
    return sorted(paths)


def pypi_versions_from_lock(lock_path: Path) -> dict[str, str]:
    """Map normalized PyPI name -> pinned version from hashed lock."""
    out: dict[str, str] = {}
    for line in lock_path.read_text(encoding="utf-8").splitlines():
        m = PKG_LINE.match(line.strip())
        if not m:
            continue
        name, version = m.group(1), m.group(2)
        out[normalize_name(name)] = version
    return out


def local_paths_from_manifest(manifest_path: Path) -> dict[str, str]:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    packages = data.get("packages", {})
    if not isinstance(packages, dict) or not packages:
        raise ValueError("local manifest empty or invalid")
    expected = set(local_editable_paths_from_in())
    seen = set(packages.keys())
    if seen != expected:
        missing = expected - seen
        extra = seen - expected
        msg = "local manifest incomplete"
        if missing:
            msg += f" missing={sorted(missing)[:5]}"
        if extra:
            msg += f" extra={sorted(extra)[:5]}"
        raise ValueError(msg)
    out: dict[str, str] = {}
    for rel in sorted(packages):
        sha = packages[rel].get("sha256", "")
        if not sha or len(sha) != 64:
            raise ValueError(f"bad digest for {rel}")
        out[rel] = sha
    return out


def _installed_package_name(rel_dir: Path) -> str | None:
    parts = rel_dir.parts
    for idx in range(len(parts) - 1, -1, -1):
        if parts[idx] != "node_modules":
            continue
        tail = parts[idx + 1 :]
        if not tail:
            return None
        if tail[0].startswith("@"):
            if len(tail) < 2:
                return None
            return f"{tail[0]}/{tail[1]}"
        return tail[0]
    if len(parts) in (1, 2) and parts[0].startswith("@") and len(parts) == 2:
        return f"{parts[0]}/{parts[1]}"
    if len(parts) == 1:
        return parts[0]
    return None


def _package_dir_matches_name(name: str, rel_dir: Path) -> bool:
    installed = _installed_package_name(rel_dir)
    return installed == name


def packages_in_bundle_node_modules(nm: Path) -> dict[str, str]:
    if not nm.is_dir():
        raise ValueError(f"missing node_modules: {nm}")
    out: dict[str, str] = {}
    for pkg_json in nm.rglob("package.json"):
        rel = pkg_json.relative_to(nm)
        if rel.name != "package.json":
            continue
        rel_dir = rel.parent
        if any(part == "_" or part.startswith("_") for part in rel_dir.parts):
            continue
        data = json.loads(pkg_json.read_text(encoding="utf-8"))
        name = str(data.get("name", "")).strip()
        version = str(data.get("version", "")).strip()
        if not name or not version:
            continue
        if not _package_dir_matches_name(name, rel_dir):
            continue
        out[name] = version
    return out


def graph_platform_fingerprint(graph_path: Path) -> dict[str, str | int]:
    data = json.loads(graph_path.read_text(encoding="utf-8"))
    rows = data.get("packages", [])
    return {
        "platform": str(data.get("platform", "")),
        "machine": str(data.get("machine", "")),
        "package_count": len(rows),
    }


def _lock_packages(lock_path: Path) -> dict[str, dict]:
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    return lock.get("packages", {}) or {}


def lock_meta_for_package(lock_path: Path, name: str, version: str) -> dict[str, str]:
    packages = _lock_packages(lock_path)
    for key, meta in packages.items():
        if not key.startswith("node_modules/"):
            continue
        pkg_name = key.split("node_modules/")[-1]
        if pkg_name != name:
            continue
        if str(meta.get("version", "")) != version:
            continue
        lic = meta.get("license")
        if isinstance(lic, dict):
            lic = lic.get("type", "")
        return {
            "version": version,
            "licenses": str(lic or ""),
            "resolved": str(meta.get("resolved", "")),
        }
    return {"version": "", "licenses": "", "resolved": ""}


def studio_npm_graph(
    package_lock_path: Path,
    graph_path: Path | None = None,
) -> dict[str, dict[str, str]]:
    path = graph_path or NPM_GRAPH
    if not path.is_file():
        raise ValueError(f"missing committed npm graph: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("packages", [])
    if not rows:
        raise ValueError("committed npm graph empty")
    graph: dict[str, dict[str, str]] = {}
    for row in rows:
        name = str(row.get("name", "")).strip()
        version = str(row.get("version", "")).strip()
        if not name or not version:
            raise ValueError(f"invalid npm graph row: {row}")
        meta = lock_meta_for_package(package_lock_path, name, version)
        if not meta.get("version"):
            raise ValueError(f"npm graph entry not in package-lock: {name}=={version}")
        lic = str(meta.get("licenses", "")).strip()
        graph[name] = {
            "version": version,
            "licenses": lic,
            "resolved": meta.get("resolved", ""),
        }
    if "sharp" not in graph or "next" not in graph:
        raise ValueError("npm graph missing required next/sharp entries")
    return graph
