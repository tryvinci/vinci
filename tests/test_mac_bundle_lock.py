from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAC = ROOT / "scripts/mac"


def _env(npm_notice_dir: Path) -> dict[str, str]:
    """Point the scripts at the fixture npm graph + notices (see conftest ``npm_notice_dir``)."""
    return {**os.environ, "VINCI_MAC_NPM_NOTICE_DIR": str(npm_notice_dir)}


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


def test_local_manifest_matches_requirements_in() -> None:
    """The committed tree list equals the -e entries; it has no digests to go stale."""
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts/mac/verify-python-local-manifest.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    manifest = json.loads((MAC / "python-bundle-local.manifest.json").read_text(encoding="utf-8"))
    assert all(isinstance(rel, str) for rel in manifest["packages"])
    assert "sha256" not in json.dumps(manifest)


def test_local_tree_hash_is_deterministic(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("hash_local", MAC / "hash-python-local-trees.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg/mod.py").write_text("x = 1\n", encoding="utf-8")
    first = mod.tree_sha256(tmp_path)
    assert mod.tree_sha256(tmp_path) == first
    (tmp_path / "pkg/__pycache__").mkdir()
    (tmp_path / "pkg/__pycache__/mod.cpython-312.pyc").write_bytes(b"cache")
    assert mod.tree_sha256(tmp_path) == first
    (tmp_path / "pkg/mod.py").write_text("x = 2\n", encoding="utf-8")
    assert mod.tree_sha256(tmp_path) != first


def _run_verify_local_manifest(manifest: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts/mac/verify-python-local-manifest.py"), str(manifest)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


def test_local_manifest_rejects_empty_packages(tmp_path: Path) -> None:
    bad = tmp_path / "bad.manifest.json"
    bad.write_text(json.dumps({"schema": 2, "packages": []}), encoding="utf-8")
    proc = _run_verify_local_manifest(bad)
    assert proc.returncode != 0
    assert "invalid" in proc.stderr.lower() or "incomplete" in proc.stderr.lower()


def test_local_manifest_rejects_missing_editable(tmp_path: Path) -> None:
    src = json.loads(
        (ROOT / "scripts/mac/python-bundle-local.manifest.json").read_text(encoding="utf-8")
    )
    bad = tmp_path / "bad.manifest.json"
    bad.write_text(json.dumps({"schema": 2, "packages": src["packages"][1:]}), encoding="utf-8")
    proc = _run_verify_local_manifest(bad)
    assert proc.returncode != 0
    assert "incomplete" in proc.stderr.lower() or "count" in proc.stderr.lower()


def test_studio_npm_graph_includes_sharp(npm_notice_dir: Path) -> None:
    graph_path = npm_notice_dir / "studio-bundle-npm-graph.json"
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    names = {p["name"] for p in graph["packages"]}
    assert "sharp" in names
    assert "next" in names
    assert len(names) >= 20


def test_npm_graph_verify_rejects_stale_graph(tmp_path: Path, npm_notice_dir: Path) -> None:
    graph_path = npm_notice_dir / "studio-bundle-npm-graph.json"
    src = json.loads(graph_path.read_text(encoding="utf-8"))
    src["packages"] = [p for p in src["packages"] if p["name"] != "sharp"]
    bad = tmp_path / "bad-graph.json"
    bad.write_text(json.dumps(src), encoding="utf-8")
    verify = str(MAC / "verify-studio-bundle-npm-graph.py")
    proc = subprocess.run(
        [sys.executable, verify, str(bad), str(npm_notice_dir / "bundle")],
        cwd=ROOT,
        env=_env(npm_notice_dir),
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


def test_notices_inputs_ok(npm_notice_dir: Path) -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts/mac/verify-notices-inputs.py")],
        cwd=ROOT,
        env=_env(npm_notice_dir),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "npm" in proc.stdout and "skipped" not in proc.stdout


def test_notices_skip_npm_before_bundle_and_sbom_fails_closed(tmp_path: Path) -> None:
    """Before prepare-studio-bundle.sh (no dist/notices), verify checks Python only; sbom fails."""
    env = _env(tmp_path / "no-notices")
    proc = subprocess.run(
        [sys.executable, str(MAC / "verify-notices-inputs.py")],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "npm notice checks skipped" in proc.stdout
    assert "prepare-studio-bundle.sh" in proc.stdout
    sbom = subprocess.run(
        ["/bin/bash", "scripts/mac/generate-notices-sbom.sh", str(tmp_path / "legal")],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert sbom.returncode != 0
    assert "missing" in sbom.stderr and "studio-bundle-npm-notices.json" in sbom.stderr
    assert not (tmp_path / "legal/provenance.json").exists()


def test_notices_list_self_hosted_fonts(tmp_path: Path, npm_notice_dir: Path) -> None:
    """The app notices list each Studio font with its sha256 and carry the OFL texts."""
    out = tmp_path / "legal"
    proc = subprocess.run(
        ["/bin/bash", "scripts/mac/generate-notices-sbom.sh", str(out)],
        cwd=ROOT,
        env=_env(npm_notice_dir),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    fonts = json.loads((out / "provenance.json").read_text(encoding="utf-8"))["fonts"]
    names = sorted(f["file"] for f in fonts)
    assert names == [p.name for p in sorted((ROOT / "apps/studio/app/fonts").glob("*.woff2"))]
    assert names and all(len(f["sha256"]) == 64 and f["license"] == "OFL-1.1" for f in fonts)
    notices = (out / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert "## Fonts (Studio, SIL Open Font License 1.1)" in notices
    assert notices.count("SIL OPEN FONT LICENSE Version 1.1") == 2


def _run_verify_notices(
    py_notices: Path, npm_notice_dir: Path, npm_notices: Path | None = None
) -> subprocess.CompletedProcess[str]:
    npm = npm_notices or (npm_notice_dir / "studio-bundle-npm-notices.json")
    verify = ROOT / "scripts/mac/verify-notices-inputs.py"
    return subprocess.run(
        [sys.executable, str(verify), str(py_notices), str(npm)],
        cwd=ROOT,
        env=_env(npm_notice_dir),
        capture_output=True,
        text=True,
    )


def test_notices_rejects_stale_pypi_version(tmp_path: Path, npm_notice_dir: Path) -> None:
    src = json.loads((ROOT / "scripts/mac/python-bundle-notices.json").read_text(encoding="utf-8"))
    for row in src["pypi"]:
        if row["name"] == "setuptools":
            row["version"] = "68.1.2"
            row["license"] = "UNKNOWN"
            break
    bad = tmp_path / "bad-python-notices.json"
    bad.write_text(json.dumps(src), encoding="utf-8")
    proc = _run_verify_notices(bad, npm_notice_dir)
    assert proc.returncode != 0
    assert "stale" in proc.stderr.lower() or "invalid" in proc.stderr.lower()


def test_notices_rejects_unknown_license(tmp_path: Path, npm_notice_dir: Path) -> None:
    src = json.loads((ROOT / "scripts/mac/python-bundle-notices.json").read_text(encoding="utf-8"))
    src["pypi"][0]["license"] = "UNKNOWN"
    bad = tmp_path / "bad-python-notices.json"
    bad.write_text(json.dumps(src), encoding="utf-8")
    proc = _run_verify_notices(bad, npm_notice_dir)
    assert proc.returncode != 0
    assert "invalid" in proc.stderr.lower()


def test_notices_rejects_missing_lock_package(tmp_path: Path, npm_notice_dir: Path) -> None:
    src = json.loads((ROOT / "scripts/mac/python-bundle-notices.json").read_text(encoding="utf-8"))
    src["pypi"] = [r for r in src["pypi"] if r["name"] != "wheel"]
    bad = tmp_path / "bad-python-notices.json"
    bad.write_text(json.dumps(src), encoding="utf-8")
    proc = _run_verify_notices(bad, npm_notice_dir)
    assert proc.returncode != 0
    assert "count" in proc.stderr.lower() or "match" in proc.stderr.lower()


def test_notices_rejects_committed_local_sha(tmp_path: Path, npm_notice_dir: Path) -> None:
    src = json.loads((MAC / "python-bundle-notices.json").read_text(encoding="utf-8"))
    src["local"][0]["sha256"] = "0" * 64
    bad = tmp_path / "bad-python-notices.json"
    bad.write_text(json.dumps(src), encoding="utf-8")
    proc = _run_verify_notices(bad, npm_notice_dir)
    assert proc.returncode != 0
    assert "no sha256" in proc.stderr


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


def test_notices_rejects_stale_graph_fingerprint(tmp_path: Path, npm_notice_dir: Path) -> None:
    src = json.loads((npm_notice_dir / "studio-bundle-npm-notices.json").read_text(encoding="utf-8"))
    src["graph_fingerprint"] = {**src["graph_fingerprint"], "platform": "stale-host"}
    bad = tmp_path / "bad-npm-notices.json"
    bad.write_text(json.dumps(src), encoding="utf-8")
    proc = _run_verify_notices(MAC / "python-bundle-notices.json", npm_notice_dir, bad)
    assert proc.returncode != 0
    assert "fingerprint" in proc.stderr.lower()


def test_collect_refreshes_notices_for_platform_graph(tmp_path: Path, npm_notice_dir: Path) -> None:
    graph_path = npm_notice_dir / "studio-bundle-npm-graph.json"
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    alt = tmp_path / "darwin-graph.json"
    # A darwin graph: no linux sharp builds, and the darwin-arm64 build once.
    pkgs = [p for p in graph["packages"] if "sharp-linux" not in p["name"] and p["name"] != "@img/sharp-darwin-arm64"]
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


def test_npm_notices_match_graph(npm_notice_dir: Path) -> None:
    graph = json.loads((npm_notice_dir / "studio-bundle-npm-graph.json").read_text(encoding="utf-8"))
    notices = json.loads((npm_notice_dir / "studio-bundle-npm-notices.json").read_text(encoding="utf-8"))
    gset = {(p["name"], p["version"]) for p in graph["packages"]}
    nset = {(p["name"], p["version"]) for p in notices["packages"]}
    assert gset == nset
    assert notices.get("graph_fingerprint", {}).get("package_count") == len(graph["packages"])


def test_generate_notices_writes_nonempty_provenance(tmp_path: Path, npm_notice_dir: Path) -> None:
    """Provenance lists local trees by name and adds sha256 only from build-time digests."""
    digests = tmp_path / "digests.json"
    env = {**_env(npm_notice_dir), "VINCI_MAC_LOCAL_DIGESTS": str(digests)}

    def provenance() -> dict:
        proc = subprocess.run(
            ["/bin/bash", "scripts/mac/generate-notices-sbom.sh", str(tmp_path / "legal")],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, proc.stderr
        return json.loads((tmp_path / "legal" / "provenance.json").read_text(encoding="utf-8"))

    prov = provenance()
    assert len(prov.get("pypi", [])) >= 5
    assert len(prov.get("npm", [])) >= 5
    assert prov["pypi_local"] and all("sha256" not in row for row in prov["pypi_local"])

    hashed = subprocess.run(
        [sys.executable, str(MAC / "hash-python-local-trees.py"), "--out", str(digests)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert hashed.returncode == 0, hashed.stderr
    want = json.loads(digests.read_text(encoding="utf-8"))["packages"]
    assert {row["name"]: row["sha256"] for row in provenance()["pypi_local"]} == want
