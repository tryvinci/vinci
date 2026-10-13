from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "dist" / "studio-bundle"


@pytest.fixture(scope="module")
def studio_bundle() -> Path:
    if not (BUNDLE / "server.js").is_file():
        subprocess.run(
            ["/bin/bash", "scripts/mac/prepare-studio-bundle.sh"],
            cwd=ROOT,
            check=True,
            env={**os.environ, "NODE_ENV": "production"},
        )
    return BUNDLE


def test_proxy_requires_session_cookie(studio_bundle: Path, tmp_path: Path) -> None:
    env = os.environ.copy()
    env["VINCI_HOME"] = str(tmp_path)
    env["VINCI_SKIP_HOME_LOCK"] = "1"
    env["VINCI_BRIDGE_TOKEN"] = "bridge-secret-test"
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
        "n1",
    ]
    daemon = subprocess.Popen(
        daemon_cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    studio = None
    try:
        port = None
        collected = ""
        deadline = time.time() + 20
        while time.time() < deadline and port is None:
            if daemon.poll() is not None:
                raise AssertionError(daemon.stderr.read() if daemon.stderr else "daemon died")
            if daemon.stdout:
                chunk = daemon.stdout.read(1)
                if chunk:
                    collected += chunk
                    match = re.search(r"READY (\d+) ([^\s]+)\n", collected)
                    if match:
                        port = int(match.group(1))
            time.sleep(0.05)
        assert port is not None
        session = "studio-session-secret"
        studio_env = {
            "PORT": "4394",
            "HOSTNAME": "127.0.0.1",
            "NODE_ENV": "production",
            "VINCI_DAEMON_URL": f"http://127.0.0.1:{port}",
            "VINCI_BRIDGE_TOKEN": "bridge-secret-test",
            "VINCI_STUDIO_SESSION": session,
            "VINCI_STUDIO_HOST": "127.0.0.1:4394",
            "VINCI_STUDIO_ORIGIN": "http://127.0.0.1:4394",
            "VINCI_LAUNCH_NONCE": "n1",
        }
        node = shutil.which("node") or "node"
        studio = subprocess.Popen(
            [node, "server.js"],
            cwd=studio_bundle,
            env=studio_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        base = "http://127.0.0.1:4394"
        for _ in range(40):
            try:
                if httpx.get(base + "/", timeout=1.0).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.2)
        denied = httpx.get(base + "/vinci-api/settings", timeout=2.0)
        assert denied.status_code == 401
        readiness_no_bridge = httpx.get(base + "/api/studio-readiness", timeout=2.0)
        assert readiness_no_bridge.status_code == 401
        readiness_bridge = httpx.get(
            base + "/api/studio-readiness",
            headers={"X-Vinci-Bridge-Token": "bridge-secret-test"},
            timeout=2.0,
        )
        assert readiness_bridge.status_code == 200
        body = readiness_bridge.json()
        assert body.get("launch_nonce") == "n1"
        assert body.get("proof")
        readiness_cookie_only = httpx.get(
            base + "/api/studio-readiness",
            headers={"Cookie": f"vinci_studio_session={session}"},
            timeout=2.0,
        )
        assert readiness_cookie_only.status_code == 401
        host_bad = httpx.get(
            base + "/vinci-api/settings",
            headers={"Host": "evil.example", "Cookie": f"vinci_studio_session={session}"},
            timeout=2.0,
        )
        assert host_bad.status_code == 403
        ok = httpx.get(
            base + "/vinci-api/settings",
            headers={"Cookie": f"vinci_studio_session={session}"},
            timeout=2.0,
        )
        assert ok.status_code == 200
        cross = httpx.post(
            base + "/vinci-api/assets",
            headers={"Origin": "https://evil.example", "Cookie": f"vinci_studio_session={session}"},
            files={"file": ("x.png", b"\x89PNG\r\n", "image/png")},
            timeout=5.0,
        )
        assert cross.status_code == 403
        patch_cross = httpx.patch(
            base + "/vinci-api/settings",
            headers={
                "Origin": "https://evil.example",
                "Cookie": f"vinci_studio_session={session}",
                "Content-Type": "application/json",
            },
            content=b"{}",
            timeout=5.0,
        )
        assert patch_cross.status_code == 403
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            free_port = sock.getsockname()[1]
        no_host_env = dict(studio_env)
        no_host_env["PORT"] = str(free_port)
        no_host_env["VINCI_STUDIO_ORIGIN"] = f"http://127.0.0.1:{free_port}"
        no_host_env.pop("VINCI_STUDIO_HOST", None)
        studio_no_host = subprocess.Popen(
            [node, "server.js"],
            cwd=studio_bundle,
            env=no_host_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        base2 = f"http://127.0.0.1:{free_port}"
        try:
            for _ in range(40):
                try:
                    if httpx.get(base2 + "/", timeout=1.0).status_code == 200:
                        break
                except httpx.HTTPError:
                    time.sleep(0.2)
            missing_host = httpx.get(
                base2 + "/vinci-api/settings",
                headers={"Cookie": f"vinci_studio_session={session}"},
                timeout=2.0,
            )
            assert missing_host.status_code == 503
        finally:
            studio_no_host.terminate()
            studio_no_host.wait(timeout=10)
    finally:
        if studio is not None:
            studio.terminate()
            studio.wait(timeout=10)
        daemon.terminate()
        daemon.wait(timeout=10)
