#!/usr/bin/env python3
"""Fingerprint production npm packages in a prepared studio bundle (fail closed)."""

from __future__ import annotations

import json
import platform
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
from notice_graph import packages_in_bundle_node_modules  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
COMMITTED = ROOT / "scripts/mac/studio-bundle-npm-graph.json"


def write_graph(bundle_root: Path, out_path: Path) -> dict:
    pkgs = packages_in_bundle_node_modules(bundle_root / "node_modules")
    if len(pkgs) < 5:
        raise ValueError(f"bundle npm graph too small: {len(pkgs)}")
    rows = [{"name": n, "version": pkgs[n]} for n in sorted(pkgs)]
    payload = {
        "schema": 2,
        "source": "studio-bundle-node_modules",
        "platform": platform.system().lower(),
        "machine": platform.machine().lower(),
        "packages": rows,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: write-studio-bundle-npm-graph.py <bundle-dir> [out-json]", file=sys.stderr)
        return 2
    bundle = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else COMMITTED
    write_graph(bundle, out)
    print(f"wrote {out} ({len(json.loads(out.read_text())['packages'])} packages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
