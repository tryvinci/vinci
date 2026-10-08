"""Durable replay idempotency: no duplicate execution across wiped-home restarts."""

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


def _port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _mcp_op_id(header_op: str, tool: str) -> str:
    return f"{header_op}:mcp:tools/call:{tool}"


def _exec_count(counter_path: Path) -> int:
    if not counter_path.is_file():
        return 0
    return int(counter_path.read_text(encoding="utf-8").strip() or "0")


def _upload_asset(port: int, op: str = "idem-src") -> str:
    import httpx

    with httpx.Client(timeout=60.0) as client:
        res = client.post(
            f"http://127.0.0.1:{port}/assets",
            files={"file": ("src.png", PNG_SWATCH, "image/png")},
            headers={"X-Vinci-Operation-Id": op},
        )
        res.raise_for_status()
        return str(res.json()["id"])


def _wait_batch_done(port: int, batch_id: str) -> dict:
    last: dict = {}
    for _ in range(160):
        status, body = _http(port, "GET", f"/adapts/batch/{batch_id}")
        assert status == 200
        last = body
        if body.get("items") and body["items"][0].get("status") == "done":
            return body
        time.sleep(0.1)
    raise AssertionError(f"batch not done: {last}")


@pytest.fixture()
def idem_env(tmp_path: Path) -> dict[str, Path | str]:
    durable = tmp_path / "durable"
    durable.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    (durable / "cas").mkdir()
    counter = durable / "exec_counter.txt"
    base = {
        "VINCI_DURABLE_JOURNAL": "local",
        "VINCI_DURABLE_JOURNAL_PATH": str(durable / "ledger.sqlite"),
        "VINCI_CAS_DIR": str(durable / "cas"),
        "VINCI_HOME": str(home),
        "VINCI_CAS_BACKEND": "local",
        "VINCI_HOME_LEASE_SECONDS": "2",
        "VINCI_TEST_EXEC_COUNTER_PATH": str(counter),
    }
    return {"durable": durable, "home": home, "counter": counter, "base": base}


def _wipe_home_restarts(
    port: int,
    base: dict[str, str],
    home: Path,
    batch_id: str,
    op_id: str,
    journal_path: Path,
    restarts: int = 3,
) -> None:
    time.sleep(2)
    journal = LocalDurableJournal(journal_path)
    parent = journal.get_operation(op_id)
    assert parent is not None
    bundle = journal.get_operation(f"{op_id}:batch_bundle")
    assert bundle is not None and bundle.get("status") == "committed"
    first_run_id = None
    bundle_body = json.loads(bundle["response_json"])
    runs = bundle_body.get("runs") or []
    if runs:
        first_run_id = str(runs[0].get("id") or runs[0].get("run_id") or "")

    for _ in range(restarts):
        shutil.rmtree(home)
        home.mkdir()
        proc = _spawn(port, dict(base))
        try:
            _wait_health(port, proc)
            status = _wait_batch_done(port, batch_id)
            assert status["items"][0]["status"] == "done"
            if first_run_id:
                assert str(status["items"][0].get("run_id") or "") == first_run_id
        finally:
            _stop(proc)
        time.sleep(0.5)


def test_rest_batch_single_exec_across_repeated_home_wipes(idem_env: dict[str, Path | str]) -> None:
    port = _port()
    journal_path = idem_env["durable"] / "ledger.sqlite"
    home = idem_env["home"]
    counter = idem_env["counter"]
    base = dict(idem_env["base"])
    op_id = "idem-rest-batch"

    proc = _spawn(port, base)
    try:
        _wait_health(port, proc)
        _http(port, "POST", "/init", {"demo": True})
        asset_id = _upload_asset(port)
        status, body = _http(
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
        assert status == 200
        batch_id = str(body["batch_id"])
        _wait_batch_done(port, batch_id)
    finally:
        _stop(proc)

    assert _exec_count(counter) == 1
    _wipe_home_restarts(port, base, home, batch_id, op_id, journal_path, restarts=3)
    assert _exec_count(counter) == 1


def test_rest_batch_before_outbox_done_restart_single_exec(idem_env: dict[str, Path | str]) -> None:
    port = _port()
    journal_path = idem_env["durable"] / "ledger.sqlite"
    home = idem_env["home"]
    counter = idem_env["counter"]
    base = dict(idem_env["base"])
    op_id = "idem-rest-before-outbox"

    setup = _spawn(port, base)
    try:
        _wait_health(port, setup)
        _http(port, "POST", "/init", {"demo": True})
        asset_id = _upload_asset(port)
    finally:
        _stop(setup)

    time.sleep(2)
    killer = _spawn(port, {**base, "VINCI_TEST_EXIT_BEFORE_OUTBOX_DONE": "1"})
    batch_id = ""
    try:
        _wait_health(port, killer)
        try:
            status, body = _http(
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
            if status == 200:
                batch_id = str(body.get("batch_id") or "")
        except Exception:
            pass
    finally:
        try:
            killer.wait(timeout=45)
        except subprocess.TimeoutExpired:
            killer.kill()
        assert killer.returncode in {137, -9, None}

    time.sleep(3)
    shutil.rmtree(home)
    home.mkdir()
    proc = _spawn(port, base)
    try:
        _wait_health(port, proc)
        journal = LocalDurableJournal(journal_path)
        parent = journal.get_operation(op_id)
        assert parent is not None
        if not batch_id:
            batch_id = str(json.loads(parent["response_json"])["batch_id"])
        _wait_batch_done(port, batch_id)
    finally:
        _stop(proc)

    assert _exec_count(counter) == 1
    _wipe_home_restarts(port, base, home, batch_id, op_id, journal_path, restarts=2)
    assert _exec_count(counter) == 1


def test_mcp_adapts_batch_single_exec_and_bundle(idem_env: dict[str, Path | str]) -> None:
    port = _port()
    journal_path = idem_env["durable"] / "ledger.sqlite"
    home = idem_env["home"]
    counter = idem_env["counter"]
    base = dict(idem_env["base"])
    header_op = "idem-mcp-batch"
    op_id = _mcp_op_id(header_op, "vinci.adapts_run")

    proc = _spawn(port, base)
    try:
        _wait_health(port, proc)
        _http(port, "POST", "/init", {"demo": True})
        asset_id = _upload_asset(port)
        import httpx

        with httpx.Client(timeout=120.0) as client:
            res = client.post(
                f"http://127.0.0.1:{port}/mcp",
                json={
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
                headers={"X-Vinci-Operation-Id": header_op},
            )
            assert res.status_code == 200, res.text
            envelope = res.json()
        intent = envelope.get("ledger_batch_intent") or {}
        text = envelope["result"]["content"][0]["text"]
        batch_id = str(intent.get("batch_id") or json.loads(text)["batch_id"])
        _wait_batch_done(port, batch_id)
    finally:
        _stop(proc)

    journal = LocalDurableJournal(journal_path)
    assert journal.get_operation(f"{op_id}:batch_bundle") is not None
    assert _exec_count(counter) == 1
    _wipe_home_restarts(port, base, home, batch_id, op_id, journal_path, restarts=2)
    assert _exec_count(counter) == 1


def test_mcp_deferred_run_bundle_before_outbox_done(idem_env: dict[str, Path | str]) -> None:
    port = _port()
    journal_path = idem_env["durable"] / "ledger.sqlite"
    home = idem_env["home"]
    counter = idem_env["counter"]
    base = dict(idem_env["base"])
    header_op = "idem-mcp-run-pre-done"
    op_id = _mcp_op_id(header_op, "vinci.image_generate")

    setup = _spawn(port, base)
    try:
        _wait_health(port, setup)
        _http(port, "POST", "/init", {"demo": True})
    finally:
        _stop(setup)

    time.sleep(2)
    killer = _spawn(port, {**base, "VINCI_TEST_EXIT_BEFORE_OUTBOX_DONE": "1"})
    run_id = ""
    try:
        _wait_health(port, killer)
        try:
            status, envelope = _http(
                port,
                "POST",
                "/mcp",
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "vinci.image_generate",
                        "arguments": {"prompt": "idem mcp run", "max_cost": 1},
                    },
                },
                headers={"X-Vinci-Operation-Id": header_op},
            )
            if status == 200:
                run_id = json.loads(envelope["result"]["content"][0]["text"])["id"]
        except Exception:
            pass
    finally:
        try:
            killer.wait(timeout=45)
        except subprocess.TimeoutExpired:
            killer.kill()

    time.sleep(3)
    shutil.rmtree(home)
    home.mkdir()
    proc = _spawn(port, base)
    try:
        _wait_health(port, proc)
        journal = LocalDurableJournal(journal_path)
        bundle = journal.get_operation(f"{op_id}:mcp_bundle")
        assert bundle is not None and bundle.get("status") == "committed"
        if not run_id:
            parent = journal.get_operation(op_id)
            assert parent is not None
            run_id = json.loads(parent["response_json"])["result"]["content"][0]["text"]
            run_id = json.loads(run_id)["id"]
        status, run = _http(port, "GET", f"/runs/{run_id}")
        assert status == 200
        assert run.get("state") == "completed"
    finally:
        _stop(proc)

    assert _exec_count(counter) == 1
    for _ in range(2):
        shutil.rmtree(home)
        home.mkdir()
        proc2 = _spawn(port, base)
        try:
            _wait_health(port, proc2)
            status, run = _http(port, "GET", f"/runs/{run_id}")
            assert status == 200
            assert run.get("state") == "completed"
        finally:
            _stop(proc2)
    assert _exec_count(counter) == 1


def test_cancelled_run_not_resurrected_on_replay(idem_env: dict[str, Path | str]) -> None:
    port = _port()
    home = idem_env["home"]
    counter = idem_env["counter"]
    base = dict(idem_env["base"])

    proc = _spawn(port, base)
    run_id = ""
    try:
        _wait_health(port, proc)
        _http(port, "POST", "/init", {"demo": True})
        status, parked = _http(
            port,
            "POST",
            "/runs",
            {
                "skill": "@tryvinci/image-generate",
                "inputs": {"prompt": "cancel idem"},
                "max_cost": -0.01,
            },
            headers={"X-Vinci-Operation-Id": "idem-park"},
        )
        assert status == 200
        run_id = str(parked["id"])
        cancel_status, _ = _http(
            port,
            "POST",
            "/mcp",
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "vinci.jobs_cancel",
                    "arguments": {"run_id": run_id},
                },
            },
            headers={"X-Vinci-Operation-Id": "idem-cancel"},
        )
        assert cancel_status == 200
    finally:
        _stop(proc)

    assert _exec_count(counter) == 0
    for _ in range(2):
        shutil.rmtree(home)
        home.mkdir()
        proc2 = _spawn(port, base)
        try:
            _wait_health(port, proc2)
            status, run = _http(port, "GET", f"/runs/{run_id}")
            assert status == 200
            assert run.get("state") == "cancelled"
        finally:
            _stop(proc2)
    assert _exec_count(counter) == 0


def test_rest_multi_item_batch_single_exec_per_item(idem_env: dict[str, Path | str]) -> None:
    port = _port()
    journal_path = idem_env["durable"] / "ledger.sqlite"
    home = idem_env["home"]
    counter = idem_env["counter"]
    base = dict(idem_env["base"])
    op_id = "idem-rest-multi"

    proc = _spawn(port, base)
    try:
        _wait_health(port, proc)
        _http(port, "POST", "/init", {"demo": True})
        a1 = _upload_asset(port, "m1")
        a2 = _upload_asset(port, "m2")
        status, body = _http(
            port,
            "POST",
            "/adapts/batch",
            {
                "items": [
                    {"asset_id": a1, "preset_ids": ["instagram_feed"]},
                    {"asset_id": a2, "preset_ids": ["instagram_feed"]},
                ],
                "fit_mode": "pad",
                "layout": "fit_pad_crop",
            },
            headers={"X-Vinci-Operation-Id": op_id},
        )
        assert status == 200
        batch_id = str(body["batch_id"])
        status_body = _wait_batch_done(port, batch_id)
        assert all(item.get("status") == "done" for item in status_body["items"])
    finally:
        _stop(proc)

    assert _exec_count(counter) == 2
    journal = LocalDurableJournal(journal_path)
    bundle = json.loads(journal.get_operation(f"{op_id}:batch_bundle")["response_json"])
    run_ids = [str(r.get("id")) for r in bundle.get("runs") or []]
    assert len(run_ids) == 2
    _wipe_home_restarts(port, base, home, batch_id, op_id, journal_path, restarts=2)
    assert _exec_count(counter) == 2
