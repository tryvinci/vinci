from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_smoke_app_linux_pending() -> None:
    script = ROOT / "scripts" / "mac" / "smoke-app.sh"
    proc = subprocess.run(
        ["/bin/bash", str(script), "/tmp/fake.app"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert "pending" in proc.stdout + proc.stderr or "requires" in proc.stdout + proc.stderr


def test_smoke_app_invokes_harness_not_handwritten_json() -> None:
    text = (ROOT / "scripts" / "mac" / "smoke-app.sh").read_text(encoding="utf-8")
    assert "--smoke-report" in text
    assert "--smoke-relaunch-report" in text
    assert "verify-smoke-report.py" in text
    assert "hand-written" not in text.lower() or "no hand-written" in text.lower()


def test_verify_smoke_report_rejects_minimal_fake_json(tmp_path: Path) -> None:
    fake = tmp_path / "fake.json"
    fake.write_text(json.dumps({"studio_port": 1, "mock_image_ok": True}), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "mac" / "verify-smoke-report.py"), str(fake)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1


def test_generate_notices_writes_provenance(tmp_path: Path) -> None:
    subprocess.run(
        ["/bin/bash", "scripts/mac/generate-notices-sbom.sh", str(tmp_path)],
        cwd=ROOT,
        check=True,
    )
    prov = tmp_path / "provenance.json"
    notices = tmp_path / "THIRD_PARTY_NOTICES.md"
    assert prov.is_file()
    assert notices.is_file()
    data = json.loads(prov.read_text(encoding="utf-8"))
    assert data["bundled_runtimes"]["node"]["sha256"]
    assert "placeholder" not in notices.read_text(encoding="utf-8").lower()
    assert len(data.get("pypi", [])) >= 5
    assert len(data.get("npm", [])) >= 5


def test_mac_swift_sources_include_smoke_runner() -> None:
    build = (ROOT / "scripts" / "mac" / "build-app.sh").read_text(encoding="utf-8")
    assert "SmokeRunner.swift" in build
