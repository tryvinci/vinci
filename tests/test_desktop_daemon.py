from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from vinci_daemon.app import create_app
from vinci_daemon.log_redaction import redact_text
from vinci_runtime.engine import Engine


@pytest.fixture
def desktop_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    monkeypatch.setenv("VINCI_DESKTOP", "1")
    monkeypatch.setenv("VINCI_BRIDGE_TOKEN", "test-bridge-token-abc")
    monkeypatch.setenv("VINCI_LAUNCH_NONCE", "nonce-123")
    monkeypatch.delenv("VINCI_ALLOW_LIVE_SPEND", raising=False)
    engine = Engine(tmp_path)
    engine.init_home(demo=True)
    return TestClient(create_app(engine))


def test_healthz_desktop_fields(desktop_client: TestClient) -> None:
    res = desktop_client.get("/healthz")
    assert res.status_code == 200
    body = res.json()
    assert body["desktop"] == "1"
    assert body["launch_nonce"] == "nonce-123"
    assert body["protocol_version"]
    assert int(body["pid"]) > 0


def test_bridge_auth_protects_assets(desktop_client: TestClient) -> None:
    denied = desktop_client.get("/settings")
    assert denied.status_code == 401
    ok = desktop_client.get("/settings", headers={"Authorization": "Bearer test-bridge-token-abc"})
    assert ok.status_code == 200


def test_handshake_requires_auth_in_desktop(desktop_client: TestClient) -> None:
    res = desktop_client.get("/handshake")
    assert res.status_code == 401


def test_redact_bridge_token() -> None:
    sample = "Authorization: Bearer secret-token-value"
    assert "secret-token-value" not in redact_text(sample)


def _wait_health(url: str, timeout: float = 15.0) -> dict[str, str]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            res = httpx.get(url, timeout=1.0)
            if res.status_code == 200:
                return res.json()
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise AssertionError(f"healthz not ready at {url}")


def test_desktop_main_ready_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    monkeypatch.delenv("VINCI_ALLOW_LIVE_SPEND", raising=False)
    env = os.environ.copy()
    env["VINCI_BRIDGE_TOKEN"] = "launch-token-xyz"
    env["VINCI_HOME"] = str(tmp_path)
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "vinci_daemon.app",
            "--host",
            "127.0.0.1",
            "--port",
            "0",
            "--desktop",
            "--launch-nonce",
            "ready-nonce",
            "--parent-pid",
            str(os.getpid()),
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        port: int | None = None
        nonce = ""
        deadline = time.time() + 20
        collected = ""
        while time.time() < deadline and port is None:
            if proc.poll() is not None:
                err = proc.stderr.read() if proc.stderr else ""
                raise AssertionError(f"daemon exited early: {err}")
            if proc.stdout:
                chunk = proc.stdout.read(1)
                if chunk:
                    collected += chunk
                    match = re.search(r"READY (\d+) ([^\s]+)\n", collected)
                    if match:
                        port = int(match.group(1))
                        nonce = match.group(2)
            time.sleep(0.05)
        assert port is not None
        assert nonce == "ready-nonce"
        body = _wait_health(f"http://127.0.0.1:{port}/healthz")
        assert body["launch_nonce"] == "ready-nonce"
        assert body["desktop"] == "1"
        bad = httpx.get(f"http://127.0.0.1:{port}/settings", timeout=2.0)
        assert bad.status_code == 401
        good = httpx.get(
            f"http://127.0.0.1:{port}/settings",
            headers={"Authorization": "Bearer launch-token-xyz"},
            timeout=2.0,
        )
        assert good.status_code == 200
        # Foreign listener on same port would not match nonce — simulate wrong nonce expectation
        assert body["launch_nonce"] != "foreign-nonce"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_home_lock_blocks_second_daemon(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["VINCI_HOME"] = str(tmp_path)
    env["VINCI_BRIDGE_TOKEN"] = "lock-test"
    env["VINCI_ALLOW_LIVE_SPEND"] = "0"
    daemon_cmd = [
        sys.executable,
        "-m",
        "vinci_daemon.app",
        "--host",
        "127.0.0.1",
        "--port",
        "0",
        "--desktop",
        "--launch-nonce",
        "a",
    ]
    first = subprocess.Popen(
        daemon_cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        time.sleep(2)
        second = subprocess.run(
            [sys.executable, "-m", "vinci_daemon.app", "--host", "127.0.0.1", "--port", "0"],
            env=env,
            capture_output=True,
            text=True,
        )
        assert second.returncode != 0
        assert "another Vinci daemon" in (second.stderr + second.stdout)
    finally:
        first.terminate()
        first.wait(timeout=10)
