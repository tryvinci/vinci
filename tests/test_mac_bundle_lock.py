from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAC = ROOT / "scripts/mac"


def test_python_bundle_lock_has_hashes() -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts/mac/verify-python-bundle-lock.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


def test_python_bundle_lock_rejects_missing_hash(tmp_path: Path) -> None:
    lock = ROOT / "scripts/mac/python-bundle-runtime.lock.txt"
    bad = tmp_path / "bad.lock"
    lines = []
    for line in lock.read_text(encoding="utf-8").splitlines():
        lines.append(line)
        if line.startswith("annotated-types=="):
            break
    bad.write_text("\n".join(lines) + "\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts/mac/verify-python-bundle-lock.py"), str(bad)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0


def test_local_manifest_matches_trees() -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts/mac/verify-python-local-manifest.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


def _run_verify_local_manifest(manifest: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts/mac/verify-python-local-manifest.py"), str(manifest)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


def test_local_manifest_rejects_empty_packages(tmp_path: Path) -> None:
    bad = tmp_path / "bad.manifest.json"
    bad.write_text(json.dumps({"schema": 1, "packages": {}}), encoding="utf-8")
    proc = _run_verify_local_manifest(bad)
    assert proc.returncode != 0
    assert "invalid" in proc.stderr.lower() or "incomplete" in proc.stderr.lower()


def test_local_manifest_rejects_missing_editable(tmp_path: Path) -> None:
    src = json.loads(
        (ROOT / "scripts/mac/python-bundle-local.manifest.json").read_text(encoding="utf-8")
    )
    pkgs = dict(src["packages"])
    pkgs.pop(next(iter(pkgs)))
    bad = tmp_path / "bad.manifest.json"
    bad.write_text(json.dumps({"schema": 1, "packages": pkgs}), encoding="utf-8")
    proc = _run_verify_local_manifest(bad)
    assert proc.returncode != 0
    assert "incomplete" in proc.stderr.lower() or "count" in proc.stderr.lower()


def test_studio_npm_graph_includes_sharp() -> None:
    graph_path = ROOT / "scripts/mac/studio-bundle-npm-graph.json"
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    names = {p["name"] for p in graph["packages"]}
    assert "sharp" in names
    assert "next" in names
    assert len(names) >= 20


def test_npm_graph_verify_rejects_stale_graph(tmp_path: Path) -> None:
    graph_path = ROOT / "scripts/mac/studio-bundle-npm-graph.json"
    src = json.loads(graph_path.read_text(encoding="utf-8"))
    src["packages"] = [p for p in src["packages"] if p["name"] != "sharp"]
    bad = tmp_path / "bad-graph.json"
    bad.write_text(json.dumps(src), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts/mac/verify-studio-bundle-npm-graph.py"), str(bad)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0


def test_python_bundle_lock_rejects_placeholder(tmp_path: Path) -> None:
    lock = ROOT / "scripts/mac/python-bundle-runtime.lock.txt"
    bad = tmp_path / "bad.lock"
    text = lock.read_text(encoding="utf-8").replace("sha256:", "PLACEHOLDER", 1)
    bad.write_text(text, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts/mac/verify-python-bundle-lock.py"), str(bad)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0


def test_notices_inputs_ok() -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts/mac/verify-notices-inputs.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


def _run_verify_notices(
    py_notices: Path, npm_notices: Path | None = None
) -> subprocess.CompletedProcess[str]:
    npm = npm_notices or (ROOT / "scripts/mac/studio-bundle-npm-notices.json")
    verify = ROOT / "scripts/mac/verify-notices-inputs.py"
    return subprocess.run(
        [sys.executable, str(verify), str(py_notices), str(npm)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


def test_notices_rejects_stale_pypi_version(tmp_path: Path) -> None:
    src = json.loads((ROOT / "scripts/mac/python-bundle-notices.json").read_text(encoding="utf-8"))
    for row in src["pypi"]:
        if row["name"] == "setuptools":
            row["version"] = "68.1.2"
            row["license"] = "UNKNOWN"
            break
    bad = tmp_path / "bad-python-notices.json"
    bad.write_text(json.dumps(src), encoding="utf-8")
    proc = _run_verify_notices(bad)
    assert proc.returncode != 0
    assert "stale" in proc.stderr.lower() or "invalid" in proc.stderr.lower()


def test_notices_rejects_unknown_license(tmp_path: Path) -> None:
    src = json.loads((ROOT / "scripts/mac/python-bundle-notices.json").read_text(encoding="utf-8"))
    src["pypi"][0]["license"] = "UNKNOWN"
    bad = tmp_path / "bad-python-notices.json"
    bad.write_text(json.dumps(src), encoding="utf-8")
    proc = _run_verify_notices(bad)
    assert proc.returncode != 0
    assert "invalid" in proc.stderr.lower()


def test_notices_rejects_missing_lock_package(tmp_path: Path) -> None:
    src = json.loads((ROOT / "scripts/mac/python-bundle-notices.json").read_text(encoding="utf-8"))
    src["pypi"] = [r for r in src["pypi"] if r["name"] != "wheel"]
    bad = tmp_path / "bad-python-notices.json"
    bad.write_text(json.dumps(src), encoding="utf-8")
    proc = _run_verify_notices(bad)
    assert proc.returncode != 0
    assert "count" in proc.stderr.lower() or "match" in proc.stderr.lower()


def test_packages_in_bundle_node_modules_includes_nested(tmp_path: Path) -> None:
    sys.path.insert(0, str(MAC))
    from notice_graph import packages_in_bundle_node_modules

    nm = tmp_path / "node_modules"
    parent = nm / "parent"
    parent.mkdir(parents=True)
    (parent / "package.json").write_text(
        json.dumps({"name": "parent", "version": "1.0.0"}), encoding="utf-8"
    )
    child = nm / "parent" / "node_modules" / "child"
    child.mkdir(parents=True)
    (child / "package.json").write_text(
        json.dumps({"name": "child", "version": "2.0.0"}), encoding="utf-8"
    )
    internal = nm / "@swc" / "helpers" / "_" / "internal"
    internal.mkdir(parents=True)
    (internal / "package.json").write_text(
        json.dumps({"name": "ignored-internal", "version": "0.0.0"}), encoding="utf-8"
    )
    pkgs = packages_in_bundle_node_modules(nm)
    assert pkgs == {"parent": "1.0.0", "child": "2.0.0"}


def test_notices_rejects_stale_graph_fingerprint(tmp_path: Path) -> None:
    src = json.loads((MAC / "studio-bundle-npm-notices.json").read_text(encoding="utf-8"))
    src["graph_fingerprint"] = {**src["graph_fingerprint"], "platform": "darwin"}
    bad = tmp_path / "bad-npm-notices.json"
    bad.write_text(json.dumps(src), encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            str(MAC / "verify-notices-inputs.py"),
            str(MAC / "python-bundle-notices.json"),
            str(bad),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "fingerprint" in proc.stderr.lower()


def test_collect_refreshes_notices_for_platform_graph(tmp_path: Path) -> None:
    graph_path = MAC / "studio-bundle-npm-graph.json"
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    alt = tmp_path / "darwin-graph.json"
    pkgs = [p for p in graph["packages"] if "sharp-linux" not in p["name"]]
    pkgs.append({"name": "@img/sharp-darwin-arm64", "version": "0.35.4"})
    alt.write_text(
        json.dumps(
            {
                **graph,
                "platform": "darwin",
                "machine": "arm64",
                "packages": sorted(pkgs, key=lambda r: r["name"]),
            }
        ),
        encoding="utf-8",
    )
    fixed = tmp_path / "fixed-npm-notices.json"
    proc = subprocess.run(
        [sys.executable, str(MAC / "collect-npm-notices.py"), str(fixed), str(alt)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    fixed_data = json.loads(fixed.read_text(encoding="utf-8"))
    names = {p["name"] for p in fixed_data["packages"]}
    assert "@img/sharp-darwin-arm64" in names
    assert fixed_data["graph_fingerprint"]["platform"] == "darwin"


def test_npm_notices_match_committed_graph() -> None:
    graph = json.loads((MAC / "studio-bundle-npm-graph.json").read_text(encoding="utf-8"))
    notices = json.loads((MAC / "studio-bundle-npm-notices.json").read_text(encoding="utf-8"))
    gset = {(p["name"], p["version"]) for p in graph["packages"]}
    nset = {(p["name"], p["version"]) for p in notices["packages"]}
    assert gset == nset
    assert notices.get("graph_fingerprint", {}).get("package_count") == len(graph["packages"])


def test_generate_notices_writes_nonempty_provenance(tmp_path: Path) -> None:
    proc = subprocess.run(
        ["/bin/bash", "scripts/mac/generate-notices-sbom.sh", str(tmp_path / "legal")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    prov = json.loads((tmp_path / "legal" / "provenance.json").read_text(encoding="utf-8"))
    assert len(prov.get("pypi", [])) >= 5
    assert len(prov.get("npm", [])) >= 5
