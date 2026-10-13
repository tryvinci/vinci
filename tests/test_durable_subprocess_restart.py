from __future__ import annotations

import http.client
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib import error, request

ROOT = Path(__file__).resolve().parents[1]


def _http(
    port: int,
    method: str,
    path: str,
    body: dict | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict]:
    data = None
    hdrs = {"content-type": "application/json"}
    if headers:
        hdrs.update(headers)
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        method=method,
        headers=hdrs,
    )
    try:
        with request.urlopen(req, timeout=30) as resp:  # noqa: S310
            raw = resp.read()
            return resp.status, json.loads(raw.decode("utf-8")) if raw else {}
    except error.HTTPError as exc:
        raw = exc.read()
        payload = json.loads(raw.decode("utf-8")) if raw else {}
        return exc.code, payload


def _wait_health(port: int, proc: subprocess.Popen[str], timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            logs = proc.stdout.read() if proc.stdout else ""
            raise AssertionError(f"daemon exited early ({proc.returncode}): {logs[-4000:]}")
        try:
            status, body = _http(port, "GET", "/healthz")
            if status == 200 and body.get("status") == "ok":
                return
        except Exception:
            pass
        time.sleep(0.25)
    logs = proc.stdout.read() if proc.stdout else ""
    raise AssertionError(f"daemon did not become healthy: {logs[-4000:]}")


def _daemon_python() -> str:
    venv = ROOT / ".venv" / "bin" / "python"
    return str(venv) if venv.is_file() else sys.executable


def _stop_daemon(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)


def _spawn_daemon(port: int, env: dict[str, str]) -> subprocess.Popen[str]:
    merged = {**os.environ, **env}
    return subprocess.Popen(
        [
            _daemon_python(),
            "-m",
            "uvicorn",
            "vinci_daemon.app:create_app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--factory",
        ],
        cwd=str(ROOT),
        env=merged,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def test_kill_before_commit_replays_on_fresh_home(tmp_path: Path) -> None:
    journal_path = tmp_path / "control-plane.sqlite"
    home_seed = tmp_path / "home-seed"
    home_fresh = tmp_path / "home-fresh"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base_env = {
        "VINCI_DURABLE_JOURNAL": "local",
        "VINCI_DURABLE_JOURNAL_PATH": str(journal_path),
        "VINCI_HOME_LEASE_SECONDS": "2",
    }
    seed = _spawn_daemon(
        port,
        {**base_env, "VINCI_HOME": str(home_seed)},
    )
    try:
        _wait_health(port, seed)
        status, _ = _http(port, "POST", "/init", {"demo": True})
        assert status == 200
    finally:
        _stop_daemon(seed)
        time.sleep(3)

    op_id = "settings-kill-replay-1"
    killer = _spawn_daemon(
        port,
        {
            **base_env,
            "VINCI_HOME": str(home_seed),
            "VINCI_TEST_EXIT_BEFORE_COMMIT": "1",
        },
    )
    try:
        _wait_health(port, killer)
        try:
            _http(
                port,
                "PATCH",
                "/settings",
                {"preference": "cheapest"},
                headers={"X-Vinci-Operation-Id": op_id},
            )
        except (http.client.RemoteDisconnected, ConnectionResetError):
            pass
    finally:
        killer.wait(timeout=15)
        if killer.returncode != 137:
            logs = killer.stdout.read() if killer.stdout else ""
            raise AssertionError(f"expected exit 137, got {killer.returncode}: {logs[-2000:]}")
    time.sleep(3)

    replay = _spawn_daemon(
        port,
        {**base_env, "VINCI_HOME": str(home_fresh)},
    )
    try:
        _wait_health(port, replay)
        status, body = _http(
            port,
            "PATCH",
            "/settings",
            {"preference": "cheapest"},
            headers={"X-Vinci-Operation-Id": op_id},
        )
        assert status == 200
        assert body.get("operation_id") == op_id
        assert body.get("preference") == "cheapest"
        status2, settings = _http(port, "GET", "/settings")
        assert status2 == 200
        assert settings.get("preference") == "cheapest"
    finally:
        _stop_daemon(replay)
