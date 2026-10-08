"""Submit-window free gate: loopback providers, barriers, takeover, honest resubmit bounds."""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib import error, request

import pytest
from vinci_provider_sdk.mock import PNG_SWATCH
from vinci_runtime.writer_effect_trace import count_writer_effects
from vinci_storage.backends import make_cas
from vinci_storage.durable_journal import LocalDurableJournal

from loopback_i2i_server import LoopbackI2IHandler, reset_loopback_state, start_loopback_i2i_server

ROOT = Path(__file__).resolve().parents[1]


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
        with request.urlopen(req, timeout=120) as resp:  # noqa: S310
            raw = resp.read()
            return resp.status, json.loads(raw.decode()) if raw else {}
    except error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def _wait_health(port: int, proc: subprocess.Popen[str], timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            logs = proc.stdout.read() if proc.stdout else ""
            raise AssertionError(f"daemon exited: {logs[-4000:]}")
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
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture()
def loopback_gate(tmp_path: Path) -> dict[str, Path | str | int]:
    reset_loopback_state()
    server, thread, port = start_loopback_i2i_server()
    durable = tmp_path / "durable"
    durable.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    cas_dir = durable / "cas"
    cas_dir.mkdir()
    output_digest = make_cas(cas_dir).put(PNG_SWATCH)
    LoopbackI2IHandler.output_digest = output_digest
    effects = durable / "effects"
    effects.mkdir()
    submit_counter = durable / "loopback_submits.txt"
    yield {
        "server": server,
        "thread": thread,
        "port": port,
        "durable": durable,
        "home": home,
        "effects": effects,
        "output_digest": output_digest,
        "submit_counter": submit_counter,
    }
    server.shutdown()
    thread.join(timeout=2)


def _loopback_env(gate: dict[str, Path | str | int], *, role: str) -> dict[str, str]:
    port = int(gate["port"])
    return {
        "VINCI_DURABLE_JOURNAL": "local",
        "VINCI_DURABLE_JOURNAL_PATH": str(gate["durable"] / "ledger.sqlite"),
        "VINCI_CAS_DIR": str(gate["durable"] / "cas"),
        "VINCI_HOME": str(gate["home"]),
        "VINCI_CAS_BACKEND": "local",
        "VINCI_HOME_LEASE_SECONDS": "2",
        "OPENAI_API_KEY": "loopback-test",
        "VINCI_TEST_LOOPBACK_I2I_URL": f"http://127.0.0.1:{port}",
        "VINCI_TEST_LOOPBACK_OUTPUT_DIGEST": str(gate["output_digest"]),
        "VINCI_TEST_LOOPBACK_SUBMIT_COUNTER_PATH": str(gate["submit_counter"]),
        "VINCI_TEST_WRITER_EFFECTS_DIR": str(gate["effects"]),
        "VINCI_TEST_WRITER_ROLE": role,
    }


def _enable_openai(port: int) -> None:
    st, body = _http(
        port,
        "POST",
        "/providers",
        {"id": "openai", "from_env": "OPENAI_API_KEY"},
        headers={"X-Vinci-Operation-Id": "enable-openai-loopback"},
    )
    assert st == 200, body


def _generate_workflow() -> dict:
    return {
        "id": "loopback-generate",
        "version": "1",
        "nodes": [
            {
                "id": "gen",
                "type": "generate",
                "capability": "t2i",
                "model_id": "openai:gpt-image-2.5-flare:2026-09",
                "params": {"prompt": "loopback gate"},
            }
        ],
    }


def test_generate_loopback_same_home_resumes_ref_without_resubmit(
    loopback_gate: dict[str, Path | str | int],
) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = _loopback_env(loopback_gate, role="owner")
    op_id = "loopback-resume-same-home"
    killer = _spawn(port, {**base, "VINCI_TEST_EXIT_AFTER_SUBMIT": "1"})
    try:
        _wait_health(port, killer)
        _http(port, "POST", "/init", {"demo": True})
        _enable_openai(port)
        try:
            import httpx

            with httpx.Client(timeout=60) as client:
                client.post(
                    f"http://127.0.0.1:{port}/runs",
                    json={"inputs": {}, "workflow": _generate_workflow()},
                    headers={"X-Vinci-Operation-Id": op_id},
                )
        except Exception:
            pass
    finally:
        try:
            killer.wait(timeout=30)
        except subprocess.TimeoutExpired:
            killer.kill()
    time.sleep(2)
    assert LoopbackI2IHandler.state.submit_count == 1
    proc = _spawn(port, base)
    try:
        _wait_health(port, proc)
        journal = LocalDurableJournal(loopback_gate["durable"] / "ledger.sqlite")
        run_id = str(json.loads(journal.get_operation(op_id)["response_json"])["id"])
        for _ in range(120):
            st, body = _http(port, "GET", f"/runs/{run_id}")
            if st == 200 and body.get("state") == "completed":
                break
            time.sleep(0.1)
        assert body.get("state") == "completed", body.get("error")
        assert journal.get_operation(f"{op_id}:output")["status"] == "committed"
    finally:
        _stop(proc)
    assert LoopbackI2IHandler.state.submit_count == 1
    effects = Path(loopback_gate["effects"])
    assert count_writer_effects(effects, role="owner", phase="submit") == 1
    assert count_writer_effects(effects, role="owner", phase="submit_resume") == 1
    assert count_writer_effects(effects, role="owner", phase="completion") == 1


def test_generate_loopback_takeover_after_submit_barrier(
    loopback_gate: dict[str, Path | str | int],
) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        stale_port = sock.getsockname()[1]
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock2:
        sock2.bind(("127.0.0.1", 0))
        owner_port = sock2.getsockname()[1]
    op_id = "loopback-takeover-generate"
    setup = _spawn(stale_port, _loopback_env(loopback_gate, role="owner"))
    try:
        _wait_health(stale_port, setup)
        _http(stale_port, "POST", "/init", {"demo": True})
        _enable_openai(stale_port)
    finally:
        _stop(setup)
    time.sleep(2)

    stale_env = {
        **_loopback_env(loopback_gate, role="stale"),
        "VINCI_TEST_DISABLE_HEARTBEAT": "1",
        "VINCI_TEST_SLEEP_AFTER_SUBMIT_MS": "4000",
    }

    def _stale_run() -> None:
        import httpx

        with httpx.Client(timeout=120) as client:
            client.post(
                f"http://127.0.0.1:{stale_port}/runs",
                json={"inputs": {}, "workflow": _generate_workflow()},
                headers={"X-Vinci-Operation-Id": op_id},
            )

    stale = _spawn(stale_port, stale_env)
    try:
        _wait_health(stale_port, stale)
        thread = threading.Thread(target=_stale_run)
        thread.start()
        time.sleep(2.4)
        owner = _spawn(
            owner_port,
            _loopback_env(loopback_gate, role="owner"),
        )
        try:
            _wait_health(owner_port, owner)
            journal = LocalDurableJournal(loopback_gate["durable"] / "ledger.sqlite")
            run_id = str(json.loads(journal.get_operation(op_id)["response_json"])["id"])
            for _ in range(160):
                st, body = _http(owner_port, "GET", f"/runs/{run_id}")
                if st == 200 and body.get("state") == "completed":
                    break
                time.sleep(0.1)
            assert body.get("state") == "completed"
            assert journal.get_operation(f"{op_id}:output")["status"] == "committed"
        finally:
            _stop(owner)
        thread.join(timeout=90)
    finally:
        _stop(stale)

    assert LoopbackI2IHandler.state.submit_count == 1
    effects = Path(loopback_gate["effects"])
    assert count_writer_effects(effects, role="stale", phase="submit") == 1
    assert count_writer_effects(effects, role="stale", phase="completion") == 0
    assert count_writer_effects(effects, role="owner", phase="submit") == 0
    assert count_writer_effects(effects, role="owner", phase="submit_resume") == 1
    assert count_writer_effects(effects, role="owner", phase="completion") == 1


def test_ai_extend_loopback_provider_branch_submit_once(
    loopback_gate: dict[str, Path | str | int],
) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = _loopback_env(loopback_gate, role="owner")
    setup = _spawn(port, base)
    try:
        _wait_health(port, setup)
        _http(port, "POST", "/init", {"demo": True})
        _enable_openai(port)
        import httpx

        with httpx.Client(timeout=60) as client:
            up = client.post(
                f"http://127.0.0.1:{port}/assets",
                files={"file": ("src.png", PNG_SWATCH, "image/png")},
                headers={"X-Vinci-Operation-Id": "ai-ext-src"},
            )
            asset_id = str(up.json()["id"])
            res = client.post(
                f"http://127.0.0.1:{port}/adapt/run",
                json={
                    "source_asset": asset_id,
                    "targets": [{"preset_id": "instagram_feed", "prompt": "extend"}],
                    "layout": "ai_extend",
                    "fit_mode": "pad",
                },
                headers={"X-Vinci-Operation-Id": "ai-ext-op"},
            )
            res.raise_for_status()
    finally:
        _stop(setup)
    assert LoopbackI2IHandler.state.submit_count == 1
    effects = Path(loopback_gate["effects"])
    assert count_writer_effects(effects, role="owner", phase="submit") == 1
    assert count_writer_effects(effects, role="owner", phase="submit_accepted") == 1


def test_generate_home_wipe_resumes_via_ledger_provider_inflight(
    loopback_gate: dict[str, Path | str | int],
) -> None:
    """Ledger :provider_inflight survives VINCI_HOME wipe (loopback reconciles)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = _loopback_env(loopback_gate, role="owner")
    op_id = "loopback-wipe-resubmit"
    killer = _spawn(port, {**base, "VINCI_TEST_EXIT_AFTER_SUBMIT": "1"})
    try:
        _wait_health(port, killer)
        _http(port, "POST", "/init", {"demo": True})
        _enable_openai(port)
        try:
            import httpx

            with httpx.Client(timeout=60) as client:
                client.post(
                    f"http://127.0.0.1:{port}/runs",
                    json={"inputs": {}, "workflow": _generate_workflow()},
                    headers={"X-Vinci-Operation-Id": op_id},
                )
        except Exception:
            pass
    finally:
        try:
            killer.wait(timeout=30)
        except subprocess.TimeoutExpired:
            killer.kill()
    journal = LocalDurableJournal(loopback_gate["durable"] / "ledger.sqlite")
    for _ in range(80):
        if journal.get_operation(op_id) is not None:
            break
        time.sleep(0.1)
    assert journal.get_operation(op_id) is not None
    shutil.rmtree(loopback_gate["home"])
    Path(loopback_gate["home"]).mkdir()
    time.sleep(2)
    proc = _spawn(port, base)
    try:
        _wait_health(port, proc)
        run_id = str(json.loads(journal.get_operation(op_id)["response_json"])["id"])
        for _ in range(120):
            st, body = _http(port, "GET", f"/runs/{run_id}")
            if st == 200 and body.get("state") == "completed":
                break
            time.sleep(0.1)
        assert body.get("state") == "completed", body.get("error")
        assert journal.get_operation(f"{op_id}:output")["status"] == "committed"
    finally:
        _stop(proc)
    assert LoopbackI2IHandler.state.submit_count == 1
    effects = Path(loopback_gate["effects"])
    resume_ledger = count_writer_effects(effects, role="owner", phase="submit_resume_ledger")
    resume_home = count_writer_effects(effects, role="owner", phase="submit_resume")
    assert resume_ledger + resume_home >= 1


def test_generate_accept_before_ledger_commit_resumes_same_home(
    loopback_gate: dict[str, Path | str | int],
) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = _loopback_env(loopback_gate, role="owner")
    op_id = "loopback-accept-ledger-gap-same-home"
    killer = _spawn(port, {**base, "VINCI_TEST_EXIT_AFTER_SUBMIT_ACCEPTED": "1"})
    try:
        _wait_health(port, killer)
        _http(port, "POST", "/init", {"demo": True})
        _enable_openai(port)
        try:
            import httpx

            with httpx.Client(timeout=60) as client:
                client.post(
                    f"http://127.0.0.1:{port}/runs",
                    json={"inputs": {}, "workflow": _generate_workflow()},
                    headers={"X-Vinci-Operation-Id": op_id},
                )
        except Exception:
            pass
    finally:
        try:
            killer.wait(timeout=30)
        except subprocess.TimeoutExpired:
            killer.kill()
    time.sleep(2)
    assert LoopbackI2IHandler.state.submit_count == 1
    journal = LocalDurableJournal(loopback_gate["durable"] / "ledger.sqlite")
    inflight_op = f"{op_id}:provider_inflight:gen"
    row = journal.get_operation(inflight_op)
    assert row is not None
    assert row["status"] == "pending"
    proc = _spawn(port, base)
    try:
        _wait_health(port, proc)
        run_id = str(json.loads(journal.get_operation(op_id)["response_json"])["id"])
        for _ in range(120):
            st, body = _http(port, "GET", f"/runs/{run_id}")
            if st == 200 and body.get("state") == "completed":
                break
            time.sleep(0.1)
        assert body.get("state") == "completed", body.get("error")
        assert journal.get_operation(inflight_op)["status"] == "committed"
    finally:
        _stop(proc)
    assert LoopbackI2IHandler.state.submit_count == 1


def test_generate_accept_before_ledger_commit_fail_closed_on_home_wipe(
    loopback_gate: dict[str, Path | str | int],
) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = _loopback_env(loopback_gate, role="owner")
    op_id = "loopback-accept-ledger-gap-wipe"
    killer = _spawn(port, {**base, "VINCI_TEST_EXIT_AFTER_SUBMIT_ACCEPTED": "1"})
    try:
        _wait_health(port, killer)
        _http(port, "POST", "/init", {"demo": True})
        _enable_openai(port)
        try:
            import httpx

            with httpx.Client(timeout=60) as client:
                client.post(
                    f"http://127.0.0.1:{port}/runs",
                    json={"inputs": {}, "workflow": _generate_workflow()},
                    headers={"X-Vinci-Operation-Id": op_id},
                )
        except Exception:
            pass
    finally:
        try:
            killer.wait(timeout=30)
        except subprocess.TimeoutExpired:
            killer.kill()
    journal = LocalDurableJournal(loopback_gate["durable"] / "ledger.sqlite")
    for _ in range(80):
        if journal.get_operation(op_id) is not None:
            break
        time.sleep(0.1)
    shutil.rmtree(loopback_gate["home"])
    Path(loopback_gate["home"]).mkdir()
    time.sleep(2)
    assert LoopbackI2IHandler.state.submit_count == 1
    proc = _spawn(port, base)
    try:
        _wait_health(port, proc)
        run_id = str(json.loads(journal.get_operation(op_id)["response_json"])["id"])
        for _ in range(120):
            st, body = _http(port, "GET", f"/runs/{run_id}")
            if st == 200 and body.get("state") in {"failed", "completed"}:
                break
            time.sleep(0.1)
        assert body.get("state") == "failed"
        err = body.get("error") or {}
        assert "fail closed" in str(err.get("message", "")).lower()
    finally:
        _stop(proc)
    assert LoopbackI2IHandler.state.submit_count == 1


def test_ledger_inflight_fail_closed_without_reconciliation(
    loopback_gate: dict[str, Path | str | int],
) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = _loopback_env(loopback_gate, role="owner")
    op_id = "loopback-fail-closed"
    killer = _spawn(port, {**base, "VINCI_TEST_EXIT_AFTER_SUBMIT": "1"})
    try:
        _wait_health(port, killer)
        _http(port, "POST", "/init", {"demo": True})
        _enable_openai(port)
        try:
            import httpx

            with httpx.Client(timeout=60) as client:
                client.post(
                    f"http://127.0.0.1:{port}/runs",
                    json={"inputs": {}, "workflow": _generate_workflow()},
                    headers={"X-Vinci-Operation-Id": op_id},
                )
        except Exception:
            pass
    finally:
        try:
            killer.wait(timeout=30)
        except subprocess.TimeoutExpired:
            killer.kill()
    journal = LocalDurableJournal(loopback_gate["durable"] / "ledger.sqlite")
    for _ in range(80):
        if journal.get_operation(op_id) is not None:
            break
        time.sleep(0.1)
    shutil.rmtree(loopback_gate["home"])
    Path(loopback_gate["home"]).mkdir()
    time.sleep(2)
    assert LoopbackI2IHandler.state.submit_count == 1
    proc = _spawn(
        port,
        {**base, "VINCI_TEST_FORCE_NO_PROVIDER_RECONCILIATION": "1"},
    )
    try:
        _wait_health(port, proc)
        run_id = str(json.loads(journal.get_operation(op_id)["response_json"])["id"])
        for _ in range(120):
            st, body = _http(port, "GET", f"/runs/{run_id}")
            if st == 200 and body.get("state") in {"failed", "completed"}:
                break
            time.sleep(0.1)
        assert body.get("state") == "failed"
        err = body.get("error") or {}
        assert "fail closed" in str(err.get("message", "")).lower()
    finally:
        _stop(proc)
    assert LoopbackI2IHandler.state.submit_count == 1
