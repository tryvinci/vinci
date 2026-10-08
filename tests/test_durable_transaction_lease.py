"""Writer lease fencing, pending output commits, and replay monotonicity."""

from __future__ import annotations

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
from fastapi.testclient import TestClient
from vinci_daemon.ledger_replay import has_run_output_receipt
from vinci_provider_sdk.mock import PNG_SWATCH
from vinci_storage.durable_journal import JournalError, LocalDurableJournal

ROOT = Path(__file__).resolve().parents[1]


def _daemon_python() -> str:
    venv = ROOT / ".venv" / "bin" / "python"
    return str(venv) if venv.is_file() else sys.executable


def test_pending_output_row_is_not_a_committed_receipt(tmp_path: Path) -> None:
    journal = LocalDurableJournal(tmp_path / "journal.sqlite")
    token = journal.acquire_writer()
    op_id = "parent-op"
    receipt_op = f"{op_id}:output"
    payload = {
        "run_id": "r1",
        "state": "completed",
        "outputs": ["abc"],
        "terminal": {"run_id": "r1", "state": "completed", "outputs": ["abc"]},
    }
    journal.prepare_operation(
        token,
        op_id=receipt_op,
        kind="run_output",
        path="/runs/r1/output",
        blob_keys=["abc"],
        payload=payload,
    )
    row = journal.get_operation(receipt_op)
    assert row is not None and row["status"] == "pending"
    assert has_run_output_receipt(journal, op_id) is False


def test_expired_lease_rejects_stale_writer_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VINCI_HOME_LEASE_SECONDS", "1")
    journal = LocalDurableJournal(tmp_path / "journal.sqlite")
    stale = journal.acquire_writer()
    time.sleep(1.2)
    journal.acquire_writer()
    with pytest.raises(JournalError, match="stale writer token|lease expired"):
        journal.commit_ack(
            stale,
            kind="settings",
            path="/settings",
            blob_keys=[],
            payload={"preference": "cheapest"},
            response={"preference": "cheapest"},
            op_id="stale-settings",
        )


def test_run_output_replay_does_not_resurrect_cancelled_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    durable = tmp_path / "durable"
    durable.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    (durable / "cas").mkdir()
    monkeypatch.setenv("VINCI_DURABLE_JOURNAL", "local")
    monkeypatch.setenv("VINCI_DURABLE_JOURNAL_PATH", str(durable / "ledger.sqlite"))
    monkeypatch.setenv("VINCI_CAS_DIR", str(durable / "cas"))
    monkeypatch.setenv("VINCI_HOME", str(home))
    monkeypatch.setenv("VINCI_CAS_BACKEND", "local")
    from vinci_daemon.app import create_app

    with TestClient(create_app()) as client:
        client.post("/init", json={"demo": True})
        parked = client.post(
            "/runs",
            json={
                "skill": "@tryvinci/image-generate",
                "inputs": {"prompt": "cancel monotonic"},
                "max_cost": -0.01,
            },
            headers={"X-Vinci-Operation-Id": "park"},
        )
        run_id = parked.json()["id"]
        client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "vinci.jobs_cancel", "arguments": {"run_id": run_id}},
            },
            headers={"X-Vinci-Operation-Id": "cancel-op"},
        )
        fake_output = {
            "op_id": "park:output",
            "kind": "run_output",
            "status": "committed",
            "payload_json": "{}",
            "blob_keys_json": "[]",
            "response_json": json.dumps(
                {
                    "run_id": run_id,
                    "state": "completed",
                    "outputs": [],
                    "jobs": [],
                    "receipts": [],
                    "assets": [],
                }
            ),
        }
        from vinci_daemon.ledger_replay import apply_committed_operation

        apply_committed_operation(client.app.state.engine, fake_output)
        run = client.get(f"/runs/{run_id}").json()
        assert run.get("state") == "cancelled"


def _http(port: int, method: str, path: str, body: dict | None = None, headers: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    hdrs = {"content-type": "application/json"}
    if headers:
        hdrs.update(headers)
    req = request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        method=method,
        headers=hdrs,
    )
    try:
        with request.urlopen(req, timeout=60) as resp:  # noqa: S310
            raw = resp.read()
            return resp.status, json.loads(raw.decode()) if raw else {}
    except error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


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
            raise AssertionError(f"daemon exited early: {logs[-4000:]}")
        try:
            st, body = _http(port, "GET", "/healthz")
            if st == 200 and body.get("status") == "ok":
                return
        except Exception:
            pass
        time.sleep(0.25)
    raise AssertionError("health timeout")


def _stop(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=15)


def test_output_prepare_kill_resume_single_exec_after_home_wipe(tmp_path: Path) -> None:
    durable = tmp_path / "durable"
    durable.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    (durable / "cas").mkdir()
    counter = durable / "counter.txt"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = {
        "VINCI_DURABLE_JOURNAL": "local",
        "VINCI_DURABLE_JOURNAL_PATH": str(durable / "ledger.sqlite"),
        "VINCI_CAS_DIR": str(durable / "cas"),
        "VINCI_HOME": str(home),
        "VINCI_CAS_BACKEND": "local",
        "VINCI_HOME_LEASE_SECONDS": "2",
        "VINCI_TEST_EXEC_COUNTER_PATH": str(counter),
    }
    op_id = "prepare-output-rest"
    setup = _spawn(port, base)
    try:
        _wait_health(port, setup)
        import httpx

        with httpx.Client(timeout=60) as client:
            client.post(f"http://127.0.0.1:{port}/init", json={"demo": True})
            up = client.post(
                f"http://127.0.0.1:{port}/assets",
                files={"file": ("src.png", PNG_SWATCH, "image/png")},
                headers={"X-Vinci-Operation-Id": "src"},
            )
            asset_id = up.json()["id"]
    finally:
        _stop(setup)
    time.sleep(2)
    killer = _spawn(port, {**base, "VINCI_TEST_EXIT_AFTER_OUTPUT_PREPARE": "1"})
    try:
        _wait_health(port, killer)
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
            killer.wait(timeout=45)
        except subprocess.TimeoutExpired:
            killer.kill()
    journal = LocalDurableJournal(durable / "ledger.sqlite")
    assert journal.get_operation(f"{op_id}:item:0:output") is not None
    assert journal.get_operation(f"{op_id}:item:0:output")["status"] == "pending"
    shutil.rmtree(home)
    home.mkdir()
    time.sleep(2)
    proc = _spawn(port, base)
    try:
        _wait_health(port, proc)
        batch_id = json.loads(journal.get_operation(op_id)["response_json"])["batch_id"]
        for _ in range(120):
            st, body = _http(port, "GET", f"/adapts/batch/{batch_id}")
            if st == 200 and body["items"][0]["status"] == "done":
                break
            time.sleep(0.1)
        assert body["items"][0]["status"] == "done"
        assert journal.get_operation(f"{op_id}:item:0:output")["status"] == "committed"
    finally:
        _stop(proc)
    assert int(counter.read_text()) == 1


def test_erased_home_startup_outbox_idle_exceeds_short_lease(tmp_path: Path) -> None:
    """Queued outbox replay on startup must hold lease while idle > lease seconds."""
    durable = tmp_path / "durable"
    durable.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    (durable / "cas").mkdir()
    counter = durable / "counter.txt"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = {
        "VINCI_DURABLE_JOURNAL": "local",
        "VINCI_DURABLE_JOURNAL_PATH": str(durable / "ledger.sqlite"),
        "VINCI_CAS_DIR": str(durable / "cas"),
        "VINCI_HOME": str(home),
        "VINCI_CAS_BACKEND": "local",
        "VINCI_HOME_LEASE_SECONDS": "2",
        "VINCI_TEST_EXEC_COUNTER_PATH": str(counter),
    }
    op_id = "startup-idle-lease"
    setup = _spawn(port, base)
    try:
        _wait_health(port, setup)
        import httpx

        with httpx.Client(timeout=60) as client:
            client.post(f"http://127.0.0.1:{port}/init", json={"demo": True})
            asset_id = client.post(
                f"http://127.0.0.1:{port}/assets",
                files={"file": ("src.png", PNG_SWATCH, "image/png")},
                headers={"X-Vinci-Operation-Id": "src"},
            ).json()["id"]
    finally:
        _stop(setup)
    time.sleep(2)
    killer = _spawn(port, {**base, "VINCI_TEST_EXIT_AFTER_ACK": "1"})
    try:
        _wait_health(port, killer)
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
            killer.wait(timeout=30)
        except subprocess.TimeoutExpired:
            killer.kill()
    shutil.rmtree(home)
    home.mkdir()
    time.sleep(2)
    proc = _spawn(
        port,
        {
            **base,
            "VINCI_TEST_SLEEP_DURING_STARTUP_OUTBOX_MS": "2500",
        },
    )
    try:
        _wait_health(port, proc)
        journal = LocalDurableJournal(durable / "ledger.sqlite")
        batch_id = json.loads(journal.get_operation(op_id)["response_json"])["batch_id"]
        for _ in range(120):
            st, body = _http(port, "GET", f"/adapts/batch/{batch_id}")
            if st == 200 and body["items"][0]["status"] == "done":
                break
            time.sleep(0.1)
        assert body["items"][0]["status"] == "done"
        assert journal.get_operation(f"{op_id}:batch_bundle") is not None
    finally:
        _stop(proc)
    assert int(counter.read_text()) == 1


def test_takeover_fences_stale_writer_mid_startup_outbox(tmp_path: Path) -> None:
    durable = tmp_path / "durable"
    durable.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    (durable / "cas").mkdir()
    counter = durable / "counter.txt"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        stale_port = sock.getsockname()[1]
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock2:
        sock2.bind(("127.0.0.1", 0))
        owner_port = sock2.getsockname()[1]
    base = {
        "VINCI_DURABLE_JOURNAL": "local",
        "VINCI_DURABLE_JOURNAL_PATH": str(durable / "ledger.sqlite"),
        "VINCI_CAS_DIR": str(durable / "cas"),
        "VINCI_HOME": str(home),
        "VINCI_CAS_BACKEND": "local",
        "VINCI_HOME_LEASE_SECONDS": "2",
        "VINCI_TEST_EXEC_COUNTER_PATH": str(counter),
    }
    op_id = "takeover-batch"
    setup = _spawn(stale_port, base)
    try:
        _wait_health(stale_port, setup)
        import httpx

        with httpx.Client(timeout=60) as client:
            client.post(f"http://127.0.0.1:{stale_port}/init", json={"demo": True})
            asset_id = client.post(
                f"http://127.0.0.1:{stale_port}/assets",
                files={"file": ("src.png", PNG_SWATCH, "image/png")},
                headers={"X-Vinci-Operation-Id": "src2"},
            ).json()["id"]
    finally:
        _stop(setup)
    time.sleep(2)
    killer = _spawn(stale_port, {**base, "VINCI_TEST_EXIT_AFTER_ACK": "1"})
    try:
        _wait_health(stale_port, killer)
        import httpx

        with httpx.Client(timeout=60) as client:
            client.post(
                f"http://127.0.0.1:{stale_port}/adapts/batch",
                json={
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
            killer.wait(timeout=30)
        except subprocess.TimeoutExpired:
            killer.kill()
    shutil.rmtree(home)
    home.mkdir()
    time.sleep(2)

    import threading

    stale_failed: list[bool] = []

    def _start_stale() -> None:
        proc = _spawn(
            stale_port,
            {
                **base,
                "VINCI_TEST_DISABLE_HEARTBEAT": "1",
                "VINCI_TEST_SLEEP_DURING_STARTUP_OUTBOX_MS": "3500",
            },
        )
        try:
            _wait_health(stale_port, proc, timeout=8.0)
            stale_failed.append(False)
        except AssertionError:
            stale_failed.append(True)
        finally:
            _stop(proc)

    thread = threading.Thread(target=_start_stale)
    thread.start()
    time.sleep(2.4)
    owner = _spawn(owner_port, base)
    try:
        _wait_health(owner_port, owner)
        journal = LocalDurableJournal(durable / "ledger.sqlite")
        batch_id = json.loads(journal.get_operation(op_id)["response_json"])["batch_id"]
        for _ in range(120):
            st, body = _http(owner_port, "GET", f"/adapts/batch/{batch_id}")
            if st == 200 and body["items"][0]["status"] == "done":
                break
            time.sleep(0.1)
        assert body["items"][0]["status"] == "done"
        assert journal.get_operation(f"{op_id}:batch_bundle") is not None
    finally:
        _stop(owner)
    thread.join(timeout=45)
    assert stale_failed and stale_failed[0] is True
    assert int(counter.read_text()) == 1


def test_heartbeat_survives_slow_adapt_execute_under_short_lease(tmp_path: Path) -> None:
    durable = tmp_path / "durable"
    durable.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    (durable / "cas").mkdir()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = {
        "VINCI_DURABLE_JOURNAL": "local",
        "VINCI_DURABLE_JOURNAL_PATH": str(durable / "ledger.sqlite"),
        "VINCI_CAS_DIR": str(durable / "cas"),
        "VINCI_HOME": str(home),
        "VINCI_CAS_BACKEND": "local",
        "VINCI_HOME_LEASE_SECONDS": "2",
        "VINCI_TEST_SLEEP_DURING_EXECUTE_MS": "2500",
    }
    proc = _spawn(port, base)
    try:
        _wait_health(port, proc)
        import httpx

        with httpx.Client(timeout=120) as client:
            client.post(f"http://127.0.0.1:{port}/init", json={"demo": True})
            up = client.post(
                f"http://127.0.0.1:{port}/assets",
                files={"file": ("src.png", PNG_SWATCH, "image/png")},
                headers={"X-Vinci-Operation-Id": "slow-src"},
            )
            asset_id = up.json()["id"]
            batch = client.post(
                f"http://127.0.0.1:{port}/adapts/batch",
                json={
                    "items": [{"asset_id": asset_id, "preset_ids": ["instagram_feed"]}],
                    "fit_mode": "pad",
                    "layout": "fit_pad_crop",
                },
                headers={"X-Vinci-Operation-Id": "slow-batch"},
            )
            assert batch.status_code == 200
            batch_id = batch.json()["batch_id"]
        for _ in range(120):
            st, body = _http(port, "GET", f"/adapts/batch/{batch_id}")
            if st == 200 and body["items"][0]["status"] == "done":
                break
            time.sleep(0.1)
        assert body["items"][0]["status"] == "done"
    finally:
        _stop(proc)
