#!/usr/bin/env python3
"""Collect production npm licenses for Studio from package-lock.json (fail closed)."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
from notice_graph import graph_platform_fingerprint, studio_npm_graph  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "scripts/mac/studio-bundle-npm-notices.json"
GRAPH = ROOT / "scripts/mac/studio-bundle-npm-graph.json"
LOCK = ROOT / "package-lock.json"
LICENSE_BAD = re.compile(r"^(UNKNOWN|unknown|)$")


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT
    graph_path = Path(sys.argv[2]) if len(sys.argv) > 2 else GRAPH
    if not LOCK.is_file():
        print(f"missing {LOCK}", file=sys.stderr)
        return 1
    if not graph_path.is_file():
        print(f"missing {graph_path}", file=sys.stderr)
        return 1
    graph = studio_npm_graph(LOCK, graph_path)
    entries = []
    for name in sorted(graph):
        meta = graph[name]
        version = str(meta.get("version", "")).strip()
        lic = str(meta.get("licenses", "")).strip()
        if not version or LICENSE_BAD.match(lic):
            print(f"missing npm license/version for {name}", file=sys.stderr)
            return 1
        entries.append(
            {
                "name": name,
                "version": version,
                "licenses": lic,
                "resolved": meta.get("resolved", ""),
            }
        )
    if len(entries) < 5:
        print(f"npm notices too small: {len(entries)}", file=sys.stderr)
        return 1
    payload = {
        "schema": 2,
        "graph_fingerprint": graph_platform_fingerprint(graph_path),
        "packages": entries,
    }
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(entries)} packages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
