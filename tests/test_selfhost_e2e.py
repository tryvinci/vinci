from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx
from vinci_provider_sdk.mock import PNG_SWATCH
from vinci_storage.r2_client import R2Client


def _selfhost_argv() -> list[str]:
    exe = shutil.which("vinci-selfhost")
    if exe:
        return [exe]
    return [sys.executable, "-m", "vinci_daemon.selfhost_entry"]


def _wait_health(port: int, timeout: float = 20.0) -> None:
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(f"{base}/healthz", timeout=1).status_code == 200:
                return
        except Exception:
            time.sleep(0.2)
    raise AssertionError("daemon did not become healthy")


def test_vinci_selfhost_process_restart_and_receipt(tmp_path: Path) -> None:
    home = tmp_path / "vinci"
    r2 = R2Client(bucket="e2e", mock_root=tmp_path / "r2")
    port = 18911
    env = os.environ.copy()
    env.update(
        {
            "VINCI_HOME": str(home),
            "VINCI_CAS_BACKEND": "r2",
            "VINCI_R2_MOCK_DIR": str(r2.mock_root),
            "VINCI_R2_BUCKET": "e2e",
            "VINCI_ALLOW_LIVE_SPEND": "0",
            "VINCI_SELFHOST": "1",
            "VINCI_HOME_SNAPSHOT_SECONDS": "1",
            "VINCI_DAEMON_PORT": str(port),
        }
    )
    proc = subprocess.Popen(
        _selfhost_argv(),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        _wait_health(port)
        httpx.post(f"{base}/init", json={"demo": True}, timeout=30)
        upload = httpx.post(
            f"{base}/assets",
            files={"file": ("creative.png", PNG_SWATCH, "image/png")},
            timeout=30,
        )
        assert upload.status_code == 200
        asset_id = upload.json()["id"]
        adapt = httpx.post(
            f"{base}/adapt/run",
            json={
                "source_asset": asset_id,
                "targets": [{"preset_id": "instagram_feed"}],
                "layout": "fit_pad_crop",
                "fit_mode": "pad",
            },
            timeout=60,
        )
        assert adapt.status_code == 200, adapt.text
        digests = adapt.json()["digests"]
        assert digests
        time.sleep(5)
    finally:
        proc.send_signal(signal.SIGTERM)
        out, err = proc.communicate(timeout=180)
        assert proc.returncode in {0, -15, 143}, (out, err)

    assert r2.get_bytes("home/snapshot-pointer.json") is not None

    home2 = tmp_path / "vinci2"
    home2.mkdir()
    env["VINCI_HOME"] = str(home2)
    env.pop("VINCI_R2_MOCK_DIR", None)
    env["VINCI_R2_MOCK_DIR"] = str(r2.mock_root)
    proc2 = subprocess.Popen(
        _selfhost_argv(),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        _wait_health(port)
        listing = httpx.get(f"{base}/assets", timeout=10).json()
        ids = {row["id"] for row in listing.get("assets", [])}
        assert asset_id in ids
        file_resp = httpx.get(f"{base}/assets/{asset_id}/file", timeout=10)
        assert file_resp.status_code == 200
        assert len(file_resp.content) > 100
    finally:
        proc2.send_signal(signal.SIGTERM)
        proc2.wait(timeout=180)
