from __future__ import annotations

import http.client
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib import error, request

import pytest
from vinci_provider_sdk.mock import PNG_SWATCH
from vinci_storage.durable_journal import LocalDurableJournal

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
        with request.urlopen(req, timeout=60) as resp:  # noqa: S310
            raw = resp.read()
            return resp.status, json.loads(raw.decode("utf-8")) if raw else {}
    except error.HTTPError as exc:
        raw = exc.read()
        payload = json.loads(raw.decode("utf-8")) if raw else {}
        return exc.code, payload
    except (http.client.RemoteDisconnected, ConnectionResetError):
        return 0, {}


def _daemon_python() -> str:
    venv = ROOT / ".venv" / "bin" / "python"
    return str(venv) if venv.is_file() else sys.executable


def _spawn(port: int, env: dict[str, str]) -> subprocess.Popen[str]:
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
        env={**os.environ, **env},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _wait_health(port: int, proc: subprocess.Popen[str], timeout: float = 45.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            logs = proc.stdout.read() if proc.stdout else ""
            raise AssertionError(f"daemon exited ({proc.returncode}): {logs[-4000:]}")
        try:
            status, body = _http(port, "GET", "/healthz")
            if status == 200 and body.get("status") == "ok":
                return
        except Exception:
            pass
        time.sleep(0.25)
    raise AssertionError("daemon not healthy")


def _stop(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture()
def batch_env(tmp_path: Path) -> dict[str, Path | str]:
    durable = tmp_path / "durable"
    durable.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    (durable / "cas").mkdir()
    base = {
        "VINCI_DURABLE_JOURNAL": "local",
        "VINCI_DURABLE_JOURNAL_PATH": str(durable / "ledger.sqlite"),
        "VINCI_CAS_DIR": str(durable / "cas"),
        "VINCI_HOME": str(home),
        "VINCI_CAS_BACKEND": "local",
        "VINCI_HOME_LEASE_SECONDS": "2",
    }
    return {"durable": durable, "home": home, "base": base}


def _port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _upload_asset(port: int) -> str:
    import httpx

    with httpx.Client(timeout=60.0) as client:
        res = client.post(
            f"http://127.0.0.1:{port}/assets",
            files={"file": ("src.png", PNG_SWATCH, "image/png")},
            headers={"X-Vinci-Operation-Id": "crash-batch-src"},
        )
        res.raise_for_status()
        return str(res.json()["id"])


def _assert_batch_converged(
    port: int, journal_path: Path, op_id: str, batch_id: str, home: Path
) -> None:
    journal = LocalDurableJournal(journal_path)
    parent = journal.get_operation(op_id)
    assert parent is not None and parent.get("status") == "committed"
    parent_body = json.loads(parent["response_json"])
    if str(parent.get("kind") or "") == "mcp_rpc":
        assert parent_body.get("ledger_batch_intent", {}).get("batch_file"), (
            "mcp parent must carry queued batch intent"
        )
    else:
        assert parent_body.get("batch_file"), "parent must carry queued batch intent"
    bundle = journal.get_operation(f"{op_id}:batch_bundle")
    assert bundle is not None and bundle.get("status") == "committed"
    bundle_body = json.loads(bundle["response_json"])
    assert bundle_body.get("batch_status"), "terminal bundle required"
    status, body = _http(port, "GET", f"/adapts/batch/{batch_id}")
    assert status == 200
    assert body["items"][0]["status"] == "done"
    assert (home / "batches" / f"{batch_id}.json").is_file()


def _run_batch_crash_loop(
    batch_env: dict[str, Path | str],
    extra_env: dict[str, str],
    op_id: str = "crash-batch-rest",
) -> str:
    time.sleep(3)
    port = _port()
    journal_path = batch_env["durable"] / "ledger.sqlite"
    home = batch_env["home"]
    base = dict(batch_env["base"])
    setup = _spawn(port, base)
    try:
        _wait_health(port, setup)
        _http(port, "POST", "/init", {"demo": True})
        asset_id = _upload_asset(port)
    finally:
        _stop(setup)
    time.sleep(1)

    proc = _spawn(port, {**base, **extra_env})
    batch_id = ""
    try:
        _wait_health(port, proc)
        try:
            _http(
                port,
                "POST",
                "/adapts/batch",
                {
                    "items": [{"asset_id": asset_id, "preset_ids": ["instagram_feed"]}],
                    "fit_mode": "pad",
                    "layout": "fit_pad_crop",
                },
                headers={"X-Vinci-Operation-Id": op_id},
            )
        except Exception:
            pass
    finally:
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
        assert proc.returncode in {137, -9}
    time.sleep(3)
    shutil.rmtree(home)
    home.mkdir()

    proc3 = _spawn(port, base)
    try:
        _wait_health(port, proc3)
        journal = LocalDurableJournal(journal_path)
        parent = journal.get_operation(op_id)
        assert parent is not None
        batch_id = str(json.loads(parent["response_json"])["batch_id"])
        _assert_batch_converged(port, journal_path, op_id, batch_id, home)
    finally:
        _stop(proc3)
    return batch_id


def test_rest_batch_after_ack_pre_dispatch_converges(batch_env: dict[str, Path | str]) -> None:
    _run_batch_crash_loop(
        batch_env, {"VINCI_TEST_EXIT_AFTER_ACK": "1"}, op_id="crash-rest-after-ack"
    )


def test_rest_batch_after_item_output_prebundle_converges(batch_env: dict[str, Path | str]) -> None:
    _run_batch_crash_loop(
        batch_env,
        {"VINCI_TEST_EXIT_BEFORE_OUTPUT_COMMIT": "1"},
        op_id="crash-rest-after-output",
    )


def test_rest_batch_after_bundle_prepare_precommit_converges(
    batch_env: dict[str, Path | str],
) -> None:
    _run_batch_crash_loop(
        batch_env,
        {"VINCI_TEST_EXIT_AFTER_BUNDLE_PREPARE": "1"},
        op_id="crash-rest-after-bundle-prepare",
    )


def test_rest_batch_before_outbox_done_converges(batch_env: dict[str, Path | str]) -> None:
    _run_batch_crash_loop(
        batch_env,
        {"VINCI_TEST_EXIT_BEFORE_OUTBOX_DONE": "1"},
        op_id="crash-rest-before-outbox-done",
    )


def test_mcp_adapts_batch_after_ack_converges(batch_env: dict[str, Path | str]) -> None:
    time.sleep(3)
    port = _port()
    journal_path = batch_env["durable"] / "ledger.sqlite"
    home = batch_env["home"]
    base = dict(batch_env["base"])
    op_id = "crash-mcp-adapt"
    setup = _spawn(port, base)
    try:
        _wait_health(port, setup)
        _http(port, "POST", "/init", {"demo": True})
        asset_id = _upload_asset(port)
    finally:
        _stop(setup)
    time.sleep(1)

    proc = _spawn(port, {**base, "VINCI_TEST_EXIT_AFTER_ACK": "1"})
    try:
        _wait_health(port, proc)
        try:
            _http(
                port,
                "POST",
                "/mcp",
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "vinci.adapts_run",
                        "arguments": {
                            "asset_id": asset_id,
                            "preset_ids": ["instagram_feed"],
                        },
                    },
                },
                headers={"X-Vinci-Operation-Id": op_id},
            )
        except Exception:
            pass
    finally:
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
        assert proc.returncode in {137, -9}
    time.sleep(3)
    shutil.rmtree(home)
    home.mkdir()
    proc3 = _spawn(port, base)
    try:
        _wait_health(port, proc3)
        journal = LocalDurableJournal(journal_path)
        mcp_rows = [r for r in journal.iter_committed_operations() if r["kind"] == "mcp_rpc"]
        parent_op = str(mcp_rows[-1]["op_id"])
        parent_body = json.loads(mcp_rows[-1]["response_json"])
        assert parent_body.get("ledger_batch_intent", {}).get("batch_file")
        batch_id = str(parent_body["ledger_batch_intent"]["batch_id"])
        _assert_batch_converged(port, journal_path, parent_op, batch_id, home)
    finally:
        _stop(proc3)
