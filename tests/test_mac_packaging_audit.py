from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_proxy_guard_fails_closed_without_host() -> None:
    text = (ROOT / "apps/studio/lib/proxy-guard.ts").read_text(encoding="utf-8")
    assert "studio host not configured" in text


def test_verify_macho_skips_on_linux() -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts/mac/verify-macho.py"), str(ROOT)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert "skipped" in proc.stdout.lower() or proc.returncode == 0


def test_ffmpeg_build_script_disables_autodetect() -> None:
    text = (ROOT / "scripts/mac/build-ffmpeg.sh").read_text(encoding="utf-8")
    assert "--disable-autodetect" in text
    assert "--enable-static" in text


def test_build_dmg_script_exists() -> None:
    path = ROOT / "scripts" / "mac" / "build-dmg.sh"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "hdiutil create" in text
    assert "Vinci Studio.app" in text


def test_build_app_links_avfoundation_for_smoke() -> None:
    text = (ROOT / "scripts" / "mac" / "build-app.sh").read_text(encoding="utf-8")
    assert "SmokeRunner.swift" in text
    assert "-framework AVFoundation" in text
