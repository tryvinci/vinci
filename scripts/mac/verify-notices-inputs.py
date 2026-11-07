#!/usr/bin/env python3
"""Fail closed: notice inputs must match lock/local/npm graphs exactly.

The npm graph + notices are build output in dist/notices (COREPRODUC-508 part B). Until
prepare-studio-bundle.sh writes them, only the Python inputs are checked.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
from notice_graph import (  # noqa: E402
    NPM_GRAPH,
    NPM_NOTICES,
    graph_platform_fingerprint,
    local_paths_from_manifest,
    normalize_name,
    pypi_versions_from_lock,
    studio_npm_graph,
)

ROOT = Path(__file__).resolve().parents[2]
PLACEHOLDER = re.compile(r"PLACEHOLDER", re.I)
LICENSE_BAD = re.compile(r"^(UNKNOWN|unknown|)$")


def main() -> int:
    """Check the Python notices, then the npm notices when a bundle build wrote them.

    Usage: ``verify-notices-inputs.py [python-notices.json] [npm-notices.json]``. An npm
    path on the command line must exist (``generate-notices-sbom.sh`` gives one). With no
    npm path and no default file (for example the Mac workflow check before the bundle),
    the npm checks are skipped and logged.

    Returns:
        0 when the inputs are ok, else 1.
    """
    py_path = ROOT / "scripts/mac/python-bundle-notices.json"
    npm_path = NPM_NOTICES
    if len(sys.argv) > 1:
        py_path = Path(sys.argv[1])
    if len(sys.argv) > 2:
        npm_path = Path(sys.argv[2])
    lock_path = ROOT / "scripts/mac/python-bundle-runtime.lock.txt"
    manifest_path = ROOT / "scripts/mac/python-bundle-local.manifest.json"
    pkg_lock = ROOT / "package-lock.json"
    check_npm = len(sys.argv) > 2 or npm_path.is_file()
    inputs = [py_path, lock_path, manifest_path] + ([npm_path, pkg_lock] if check_npm else [])
    for path in inputs:
        if not path.is_file():
            print(f"missing: {path}", file=sys.stderr)
            return 1
        if PLACEHOLDER.search(path.read_text(encoding="utf-8")):
            print(f"placeholder in {path}", file=sys.stderr)
            return 1

    lock_versions = pypi_versions_from_lock(lock_path)
    try:
        manifest_local = set(local_paths_from_manifest(manifest_path))
    except ValueError as exc:
        print(f"local manifest invalid: {exc}", file=sys.stderr)
        return 1
    py_data = json.loads(py_path.read_text(encoding="utf-8"))
    pypi_rows = py_data.get("pypi", [])
    local_rows = py_data.get("local", [])

    if not pypi_rows or not local_rows:
        print("empty notice section", file=sys.stderr)
        return 1

    if len(pypi_rows) != len(lock_versions):
        print(
            f"pypi notice count {len(pypi_rows)} != lock count {len(lock_versions)}",
            file=sys.stderr,
        )
        return 1

    seen_pypi: set[str] = set()
    for row in pypi_rows:
        name = row.get("name", "")
        version = row.get("version", "")
        license_ = str(row.get("license", "")).strip()
        key = normalize_name(name)
        if not name or not version or LICENSE_BAD.match(license_):
            print(f"invalid pypi notice row: {row}", file=sys.stderr)
            return 1
        if key not in lock_versions:
            print(f"pypi notice not in lock: {name}", file=sys.stderr)
            return 1
        if lock_versions[key] != version:
            print(
                f"stale pypi notice {name}: notice {version} != lock {lock_versions[key]}",
                file=sys.stderr,
            )
            return 1
        seen_pypi.add(key)

    if seen_pypi != set(lock_versions.keys()):
        print("pypi notice names do not match lock graph", file=sys.stderr)
        return 1

    seen_local: set[str] = set()
    for row in local_rows:
        rel = row.get("name", "")
        license_ = str(row.get("license", "")).strip()
        # A committed sha256 goes stale on each source edit; digests are build-time only.
        if not rel or LICENSE_BAD.match(license_) or "sha256" in row:
            print(f"invalid local notice row (name + license, no sha256): {row}", file=sys.stderr)
            return 1
        if rel not in manifest_local:
            print(f"local notice not in manifest: {rel}", file=sys.stderr)
            return 1
        seen_local.add(rel)

    if seen_local != manifest_local:
        print("local notice paths do not match manifest graph", file=sys.stderr)
        return 1

    if not check_npm:
        print(f"npm notice checks skipped: no {npm_path} (prepare-studio-bundle.sh writes it)")
        print(f"notices inputs ok (python only: {len(pypi_rows)} pypi, {len(local_rows)} local)")
        return 0

    try:
        npm_graph = studio_npm_graph(pkg_lock)
    except ValueError as exc:
        print(f"npm graph invalid: {exc}", file=sys.stderr)
        return 1
    npm_data = json.loads(npm_path.read_text(encoding="utf-8"))
    npm_fp = npm_data.get("graph_fingerprint", {})
    graph_fp = graph_platform_fingerprint(NPM_GRAPH)
    if npm_fp != graph_fp:
        print(
            f"stale npm notices fingerprint {npm_fp} != graph {graph_fp}"
            " (run scripts/mac/sync-bundle-notices.sh)",
            file=sys.stderr,
        )
        return 1
    npm_rows = npm_data.get("packages", [])
    if not npm_rows:
        print("empty notice section", file=sys.stderr)
        return 1

    if len(npm_rows) != len(npm_graph):
        print(
            f"npm notice count {len(npm_rows)} != studio graph {len(npm_graph)}",
            file=sys.stderr,
        )
        return 1

    seen_npm: set[str] = set()
    for row in npm_rows:
        name = row.get("name", "")
        version = str(row.get("version", "")).strip()
        lic = str(row.get("licenses", "")).strip()
        if not name or not version or LICENSE_BAD.match(lic):
            print(f"invalid npm notice row: {row}", file=sys.stderr)
            return 1
        if name not in npm_graph:
            print(f"npm notice not in studio graph: {name}", file=sys.stderr)
            return 1
        meta = npm_graph[name]
        if meta.get("version") != version:
            print(
                f"stale npm notice {name}: {version} != lock {meta.get('version')}",
                file=sys.stderr,
            )
            return 1
        lock_lic = str(meta.get("licenses", "")).strip()
        if lock_lic and LICENSE_BAD.match(lock_lic):
            print(f"npm lock license missing for {name}", file=sys.stderr)
            return 1
        seen_npm.add(name)

    if seen_npm != set(npm_graph.keys()):
        print("npm notice names do not match studio graph", file=sys.stderr)
        return 1

    counts = f"{len(pypi_rows)} pypi, {len(local_rows)} local, {len(npm_rows)} npm"
    print(f"notices inputs ok ({counts})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
