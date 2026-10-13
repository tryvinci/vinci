#!/usr/bin/env python3
"""Verify committed studio npm graph matches bundle tree and package-lock metadata."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
from notice_graph import (  # noqa: E402
    lock_meta_for_package,
    packages_in_bundle_node_modules,
    studio_npm_graph,
)

ROOT = Path(__file__).resolve().parents[2]
GRAPH = ROOT / "scripts/mac/studio-bundle-npm-graph.json"
LOCK = ROOT / "package-lock.json"


def main() -> int:
    graph_path = Path(sys.argv[1]) if len(sys.argv) > 1 else GRAPH
    bundle_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "dist/studio-bundle"
    if not graph_path.is_file():
        print(f"missing graph: {graph_path}", file=sys.stderr)
        return 1
    if not LOCK.is_file():
        print(f"missing lock: {LOCK}", file=sys.stderr)
        return 1
    data = json.loads(graph_path.read_text(encoding="utf-8"))
    rows = data.get("packages", [])
    if not rows:
        print("empty npm graph", file=sys.stderr)
        return 1
    committed = {r["name"]: r["version"] for r in rows if r.get("name") and r.get("version")}
    if len(committed) != len(rows):
        print("invalid npm graph rows", file=sys.stderr)
        return 1
    for name, version in committed.items():
        meta = lock_meta_for_package(LOCK, name, version)
        if not meta.get("version"):
            print(f"npm graph entry not in package-lock: {name}=={version}", file=sys.stderr)
            return 1
    if bundle_dir.is_dir() and (bundle_dir / "node_modules").is_dir():
        live = packages_in_bundle_node_modules(bundle_dir / "node_modules")
        if live != committed:
            print("committed npm graph != live studio bundle node_modules", file=sys.stderr)
            missing = set(live) - set(committed)
            extra = set(committed) - set(live)
            if missing:
                print(f"  missing from graph: {sorted(missing)[:8]}", file=sys.stderr)
            if extra:
                print(f"  extra in graph: {sorted(extra)[:8]}", file=sys.stderr)
            return 1
    expected = studio_npm_graph(LOCK, graph_path)
    if set(expected.keys()) != set(committed.keys()):
        print("studio_npm_graph keys mismatch committed graph", file=sys.stderr)
        return 1
    print(f"studio npm graph ok ({len(committed)} packages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
