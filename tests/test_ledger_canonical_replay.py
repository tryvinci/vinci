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
from fastapi.testclient import TestClient
from vinci_provider_sdk.mock import PNG_SWATCH
from vinci_storage.durable_journal import LocalDurableJournal
from vinci_storage.journal_payload import mcp_ledger_payload, payload_digest

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


def _wait_health(port: int, proc: subprocess.Popen[str], timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            logs = proc.stdout.read() if proc.stdout else ""
            raise AssertionError(f"daemon exited ({proc.returncode}): {logs[-3000:]}")
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
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture()
def durable_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
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
    return {"durable": durable, "home": home}


def _client() -> TestClient:
    from vinci_daemon.app import create_app

    return TestClient(create_app())


def test_mcp_ledger_payload_includes_tool_arguments() -> None:
    msg = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "vinci.skills_search", "arguments": {"query": "image"}},
    }
    body = mcp_ledger_payload(msg)
    assert body["tool"] == "vinci.skills_search"
    assert body["arguments"]["query"] == "image"
    slim = {"method": "tools/call", "id": 1}
    assert payload_digest(body) != payload_digest(slim)


def test_adapt_durable_replay_download_assets(durable_env: dict[str, Path]) -> None:
    with _client() as client:
        client.post("/init", json={"demo": True})
        upload = client.post(
            "/assets",
            files={"file": ("src.png", PNG_SWATCH, "image/png")},
            headers={"X-Vinci-Operation-Id": "adapt-src"},
        )
        assert upload.status_code == 200
        source_id = upload.json()["id"]
        adapt = client.post(
            "/adapt/run",
            json={
                "source_asset": source_id,
                "targets": [{"preset_id": "instagram_feed"}],
                "layout": "fit_pad_crop",
                "fit_mode": "pad",
            },
            headers={"X-Vinci-Operation-Id": "adapt-op-1"},
        )
        assert adapt.status_code == 200
        digest = adapt.json()["digests"][0]

    shutil.rmtree(durable_env["home"])
    durable_env["home"].mkdir()

    with _client() as client2:
        file_res = client2.get(f"/assets/{digest}/file")
        assert file_res.status_code == 200
        assert file_res.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_run_replay_restores_jobs_and_receipts(durable_env: dict[str, Path]) -> None:
    with _client() as client:
        client.post("/init", json={"demo": True})
        run = client.post(
            "/runs",
            json={
                "skill": "@tryvinci/image-generate",
                "inputs": {"prompt": "ledger replay cube"},
            },
            headers={"X-Vinci-Operation-Id": "run-replay-1"},
        )
        assert run.status_code == 200
        run_id = run.json()["id"]
        job_id = ""
        for _ in range(90):
            body = client.get(f"/runs/{run_id}").json()
            if body.get("state") == "completed" and body.get("job_ids"):
                job_id = body["job_ids"][0]
                break
            time.sleep(0.05)
        assert job_id

    shutil.rmtree(durable_env["home"])
    durable_env["home"].mkdir()

    with _client() as client2:
        job = client2.get(f"/jobs/{job_id}" if False else "/jobs")  # list jobs
        jobs = job.json()["jobs"]
        assert any(j["id"] == job_id for j in jobs)
        receipt = client2.get(f"/receipts/{job_id}")
        assert receipt.status_code == 200
        body = receipt.json()
        assert body.get("job_id") == job_id
        assert body.get("computed_cost") is not None
        run_res = client2.get(f"/runs/{run_id}")
        assert run_res.json().get("state") == "completed"


def test_ledger_replay_paginates_beyond_single_page(tmp_path: Path) -> None:
    journal = LocalDurableJournal(tmp_path / "big.sqlite")
    token = journal.acquire_writer()
    total = 150
    for idx in range(total):
        op = f"op-page-{idx:04d}"
        journal.prepare_operation(
            token,
            op_id=op,
            kind="settings",
            path="/settings",
            blob_keys=[],
            payload={"preference": "cheapest", "idx": idx},
        )
        journal.commit_ack(
            token,
            kind="settings",
            path="/settings",
            blob_keys=[],
            payload={"preference": "cheapest", "idx": idx},
            response={"preference": "cheapest", "idx": idx},
            op_id=op,
        )
    seen: list[str] = []
    for row in journal.iter_committed_operations(page_size=50):
        seen.append(str(row["op_id"]))
    assert len(seen) == total
    assert seen[0] == "op-page-0000"
    assert seen[-1] == f"op-page-{total - 1:04d}"


def test_repeated_replay_is_idempotent(durable_env: dict[str, Path]) -> None:
    from vinci_daemon.ledger_replay import rebuild_acknowledged_metadata
    from vinci_runtime.engine import Engine

    with _client() as client:
        client.post("/init", json={"demo": True})
        client.patch(
            "/settings",
            json={"preference": "cheapest"},
            headers={"X-Vinci-Operation-Id": "repeat-settings"},
        )

    shutil.rmtree(durable_env["home"])
    durable_env["home"].mkdir()

    journal = LocalDurableJournal(durable_env["durable"] / "ledger.sqlite")
    journal.acquire_writer()
    engine = Engine(durable_env["home"])
    n1 = rebuild_acknowledged_metadata(journal, engine)
    n2 = rebuild_acknowledged_metadata(journal, engine)
    assert n1 > 0
    assert n2 == 0
    pref = engine.config.preference
    assert (pref.value if hasattr(pref, "value") else pref) == "cheapest"


def test_ledger_replay_more_than_ten_thousand_rows(tmp_path: Path) -> None:
    journal = LocalDurableJournal(tmp_path / "tenk.sqlite")
    token = journal.acquire_writer()
    total = 10_050
    for idx in range(total):
        op = f"op-10k-{idx:05d}"
        journal.prepare_operation(
            token,
            op_id=op,
            kind="settings",
            path="/settings",
            blob_keys=[],
            payload={"idx": idx},
        )
        journal.commit_ack(
            token,
            kind="settings",
            path="/settings",
            blob_keys=[],
            payload={"idx": idx},
            response={"preference": "cheapest", "idx": idx},
            op_id=op,
        )
    count = sum(1 for _ in journal.iter_committed_operations(page_size=500))
    assert count == total


def test_kill_before_output_commit_keeps_outbox_pending(tmp_path: Path) -> None:
    journal_path = tmp_path / "journal.sqlite"
    home = tmp_path / "home"
    home.mkdir()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = {
        "VINCI_DURABLE_JOURNAL": "local",
        "VINCI_DURABLE_JOURNAL_PATH": str(journal_path),
        "VINCI_HOME": str(home),
        "VINCI_HOME_LEASE_SECONDS": "2",
        "VINCI_CAS_BACKEND": "local",
        "VINCI_TEST_EXIT_BEFORE_OUTPUT_COMMIT": "1",
    }
    proc = _spawn(port, base)
    op_id = "kill-before-output"
    try:
        _wait_health(port, proc)
        _http(port, "POST", "/init", {"demo": True})
        try:
            _http(
                port,
                "POST",
                "/runs",
                {
                    "skill": "@tryvinci/image-generate",
                    "inputs": {"prompt": "kill before output commit"},
                },
                headers={"X-Vinci-Operation-Id": op_id},
            )
        except (http.client.RemoteDisconnected, ConnectionResetError):
            pass
    finally:
        proc.wait(timeout=20)
        assert proc.returncode == 137
    time.sleep(3)

    journal = LocalDurableJournal(journal_path)
    assert not any(
        row.get("op_id") == f"{op_id}:output" and row.get("status") == "committed"
        for row in journal.iter_committed_operations(page_size=200)
    )

    replay_env = {k: v for k, v in base.items() if k != "VINCI_TEST_EXIT_BEFORE_OUTPUT_COMMIT"}
    replay = _spawn(port, replay_env)
    try:
        _wait_health(port, replay)
        for _ in range(60):
            status, body = _http(port, "GET", "/runs")
            runs = body.get("runs") or []
            if runs and runs[0].get("state") == "completed":
                break
            time.sleep(0.25)
        status, body = _http(port, "GET", "/runs")
        assert any(r.get("state") == "completed" for r in body.get("runs") or [])
        assert journal.get_operation(f"{op_id}:output") is not None
    finally:
        _stop(replay)


def test_kill_after_ack_before_dispatch_retries_outbox(tmp_path: Path) -> None:
    journal_path = tmp_path / "journal.sqlite"
    home = tmp_path / "home"
    home.mkdir()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = {
        "VINCI_DURABLE_JOURNAL": "local",
        "VINCI_DURABLE_JOURNAL_PATH": str(journal_path),
        "VINCI_HOME": str(home),
        "VINCI_HOME_LEASE_SECONDS": "2",
        "VINCI_CAS_BACKEND": "local",
    }
    proc = _spawn(port, base)
    try:
        _wait_health(port, proc)
        _http(port, "POST", "/init", {"demo": True})
    finally:
        _stop(proc)
        time.sleep(3)

    killer = _spawn(port, {**base, "VINCI_TEST_EXIT_AFTER_ACK": "1"})
    op_id = "kill-after-ack-run"
    try:
        _wait_health(port, killer)
        try:
            _http(
                port,
                "POST",
                "/runs",
                {
                    "skill": "@tryvinci/image-generate",
                    "inputs": {"prompt": "kill after ack"},
                },
                headers={"X-Vinci-Operation-Id": op_id},
            )
        except (http.client.RemoteDisconnected, ConnectionResetError):
            pass
    finally:
        killer.wait(timeout=20)
        assert killer.returncode == 137
    time.sleep(3)

    replay = _spawn(port, base)
    try:
        _wait_health(port, replay)
        status, body = _http(port, "GET", "/runs")
        assert status == 200
        runs = body.get("runs") or []
        assert any(r.get("state") == "completed" for r in runs)
        completed = next(r for r in runs if r.get("state") == "completed")
        job_id = completed["job_ids"][0]
        r_status, receipt = _http(port, "GET", f"/receipts/{job_id}")
        assert r_status == 200
        assert receipt.get("job_id") == job_id
    finally:
        _stop(replay)
