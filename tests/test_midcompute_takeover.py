"""Mid-compute lease takeover: zero stale writer effects; owner completes once."""

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
from vinci_storage.durable_journal import LocalDurableJournal

ROOT = Path(__file__).resolve().parents[1]

# HTTP ack on the stale daemon may record ledger_ack once; compute must not finish on stale.
_STALE_FORBIDDEN = (
    "execute_entry",
    "node",
    "submit",
    "cas",
    "persist_job",
    "completion",
    "run_state_completed",
    "run_state_failed",
    "run_state_running",
    "ledger_commit",
    "ai_extend",
)


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
            raise AssertionError(f"daemon exited: {logs[-3000:]}")
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


def _assert_stale_zero_compute(effects_dir: Path) -> None:
    for phase in _STALE_FORBIDDEN:
        assert count_writer_effects(effects_dir, role="stale", phase=phase) == 0, phase


def _ledger_committed(journal: LocalDurableJournal, op_id: str) -> int:
    row = journal.get_operation(op_id)
    return 1 if row and row.get("status") == "committed" else 0


@pytest.fixture()
def takeover_env(tmp_path: Path) -> dict[str, Path | str]:
    durable = tmp_path / "durable"
    durable.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    (durable / "cas").mkdir()
    effects = durable / "effects"
    effects.mkdir()
    return {
        "durable": durable,
        "home": home,
        "effects": effects,
    }


def _base_env(takeover_env: dict[str, Path | str], *, role: str) -> dict[str, str]:
    return {
        "VINCI_DURABLE_JOURNAL": "local",
        "VINCI_DURABLE_JOURNAL_PATH": str(takeover_env["durable"] / "ledger.sqlite"),
        "VINCI_CAS_DIR": str(takeover_env["durable"] / "cas"),
        "VINCI_HOME": str(takeover_env["home"]),
        "VINCI_CAS_BACKEND": "local",
        "VINCI_HOME_LEASE_SECONDS": "2",
        "VINCI_TEST_WRITER_EFFECTS_DIR": str(takeover_env["effects"]),
        "VINCI_TEST_WRITER_ROLE": role,
        "VINCI_TEST_MOCK_SUBMIT_COUNTER_PATH": str(takeover_env["durable"] / "mock_submit.txt"),
    }


def _upload(port: int, op: str = "takeover-src") -> str:
    import httpx

    with httpx.Client(timeout=60) as client:
        res = client.post(
            f"http://127.0.0.1:{port}/assets",
            files={"file": ("src.png", PNG_SWATCH, "image/png")},
            headers={"X-Vinci-Operation-Id": op},
        )
        res.raise_for_status()
        return str(res.json()["id"])


def _two_adapt_workflow(asset_id: str, *, layout: str = "fit_pad_crop") -> dict:
    node = {
        "type": "media",
        "params": {
            "op": "adapt",
            "media": asset_id,
            "preset_ids": ["instagram_feed"],
            "fit_mode": "pad",
            "layout": layout,
        },
    }
    return {
        "id": "two-adapt",
        "version": "1",
        "nodes": [{"id": "a", **node}, {"id": "b", **node}],
    }


def test_midcompute_batch_takeover_zero_stale_effects(takeover_env: dict[str, Path | str]) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        stale_port = sock.getsockname()[1]
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock2:
        sock2.bind(("127.0.0.1", 0))
        owner_port = sock2.getsockname()[1]
    op_id = "midcompute-batch"
    setup = _spawn(stale_port, _base_env(takeover_env, role="owner"))
    try:
        _wait_health(stale_port, setup)
        _http(stale_port, "POST", "/init", {"demo": True})
        asset_id = _upload(stale_port)
    finally:
        _stop(setup)
    time.sleep(2)

    stale_env = {
        **_base_env(takeover_env, role="stale"),
        "VINCI_TEST_DISABLE_HEARTBEAT": "1",
        "VINCI_TEST_SLEEP_DURING_EXECUTE_MS": "4000",
    }

    def _stale_batch() -> None:
        import httpx

        with httpx.Client(timeout=120) as client:
            client.post(
                f"http://127.0.0.1:{stale_port}/adapts/batch",
                json={
                    "items": [{"asset_id": asset_id, "preset_ids": ["instagram_feed"]}],
                    "fit_mode": "pad",
                    "layout": "fit_pad_crop",
                },
                headers={"X-Vinci-Operation-Id": op_id},
            )

    stale = _spawn(stale_port, stale_env)
    try:
        _wait_health(stale_port, stale)
        thread = threading.Thread(target=_stale_batch)
        thread.start()
        time.sleep(2.4)
        owner_home = takeover_env["durable"] / "home_owner"
        owner_home.mkdir(exist_ok=True)
        owner = _spawn(
            owner_port,
            {**_base_env(takeover_env, role="owner"), "VINCI_HOME": str(owner_home)},
        )
        try:
            _wait_health(owner_port, owner)
            journal = LocalDurableJournal(takeover_env["durable"] / "ledger.sqlite")
            batch_id = str(json.loads(journal.get_operation(op_id)["response_json"])["batch_id"])
            for _ in range(160):
                st, body = _http(owner_port, "GET", f"/adapts/batch/{batch_id}")
                if st == 200 and body["items"][0]["status"] == "done":
                    break
                time.sleep(0.1)
            assert body["items"][0]["status"] == "done"
            assert journal.get_operation(f"{op_id}:batch_bundle")["status"] == "committed"
            assert _ledger_committed(journal, op_id) == 1
        finally:
            _stop(owner)
        thread.join(timeout=90)
    finally:
        _stop(stale)

    effects = Path(takeover_env["effects"])
    _assert_stale_zero_compute(effects)
    assert count_writer_effects(effects, role="owner", phase="completion") == 1
    assert count_writer_effects(effects, role="owner", phase="node") >= 1
    assert count_writer_effects(effects, role="owner", phase="cas") >= 1
    assert count_writer_effects(effects, role="owner", phase="ledger_ack") >= 1


def test_between_nodes_takeover_zero_stale_effects(takeover_env: dict[str, Path | str]) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        stale_port = sock.getsockname()[1]
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock2:
        sock2.bind(("127.0.0.1", 0))
        owner_port = sock2.getsockname()[1]
    op_id = "between-nodes-run"
    setup = _spawn(stale_port, _base_env(takeover_env, role="owner"))
    asset_id = ""
    try:
        _wait_health(stale_port, setup)
        _http(stale_port, "POST", "/init", {"demo": True})
        asset_id = _upload(stale_port)
    finally:
        _stop(setup)
    time.sleep(2)
    workflow = _two_adapt_workflow(asset_id)

    def _stale_run() -> None:
        import httpx

        with httpx.Client(timeout=120) as client:
            client.post(
                f"http://127.0.0.1:{stale_port}/runs",
                json={"inputs": {"media": asset_id}, "workflow": workflow},
                headers={"X-Vinci-Operation-Id": op_id},
            )

    stale = _spawn(
        stale_port,
        {
            **_base_env(takeover_env, role="stale"),
            "VINCI_TEST_DISABLE_HEARTBEAT": "1",
            "VINCI_TEST_SLEEP_DURING_EXECUTE_MS": "4000",
        },
    )
    try:
        _wait_health(stale_port, stale)
        thread = threading.Thread(target=_stale_run)
        thread.start()
        time.sleep(2.4)
        owner_home = takeover_env["durable"] / "home_owner_nodes"
        owner_home.mkdir(exist_ok=True)
        owner = _spawn(
            owner_port,
            {**_base_env(takeover_env, role="owner"), "VINCI_HOME": str(owner_home)},
        )
        try:
            _wait_health(owner_port, owner)
            journal = LocalDurableJournal(takeover_env["durable"] / "ledger.sqlite")
            run_id = str(json.loads(journal.get_operation(op_id)["response_json"])["id"])
            for _ in range(160):
                st, body = _http(owner_port, "GET", f"/runs/{run_id}")
                if st == 200 and body.get("state") == "completed":
                    break
                time.sleep(0.1)
            assert body.get("state") == "completed"
            assert journal.get_operation(f"{op_id}:output")["status"] == "committed"
            effects_path = Path(takeover_env["effects"])
            assert count_writer_effects(effects_path, role="owner", phase="node") == 2
        finally:
            _stop(owner)
        thread.join(timeout=90)
    finally:
        _stop(stale)
    _assert_stale_zero_compute(Path(takeover_env["effects"]))
    effects_path = Path(takeover_env["effects"])
    assert count_writer_effects(effects_path, role="owner", phase="completion") == 1


def test_ai_extend_between_nodes_takeover(takeover_env: dict[str, Path | str]) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        stale_port = sock.getsockname()[1]
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock2:
        sock2.bind(("127.0.0.1", 0))
        owner_port = sock2.getsockname()[1]
    op_id = "ai-extend-nodes"
    setup = _spawn(stale_port, _base_env(takeover_env, role="owner"))
    try:
        _wait_health(stale_port, setup)
        _http(stale_port, "POST", "/init", {"demo": True})
        asset_id = _upload(stale_port, "ai-src")
    finally:
        _stop(setup)
    time.sleep(2)
    workflow = _two_adapt_workflow(asset_id, layout="ai_extend")

    stale = _spawn(
        stale_port,
        {
            **_base_env(takeover_env, role="stale"),
            "VINCI_TEST_DISABLE_HEARTBEAT": "1",
            "VINCI_TEST_SLEEP_DURING_EXECUTE_MS": "4000",
        },
    )

    def _stale_run() -> None:
        import httpx

        with httpx.Client(timeout=120) as client:
            client.post(
                f"http://127.0.0.1:{stale_port}/runs",
                json={"inputs": {"media": asset_id}, "workflow": workflow},
                headers={"X-Vinci-Operation-Id": op_id},
            )

    try:
        _wait_health(stale_port, stale)
        thread = threading.Thread(target=_stale_run)
        thread.start()
        time.sleep(2.4)
        owner_home = takeover_env["durable"] / "home_ai_extend"
        owner_home.mkdir(exist_ok=True)
        owner = _spawn(
            owner_port,
            {**_base_env(takeover_env, role="owner"), "VINCI_HOME": str(owner_home)},
        )
        try:
            _wait_health(owner_port, owner)
            journal = LocalDurableJournal(takeover_env["durable"] / "ledger.sqlite")
            run_id = str(json.loads(journal.get_operation(op_id)["response_json"])["id"])
            for _ in range(160):
                st, body = _http(owner_port, "GET", f"/runs/{run_id}")
                if st == 200 and body.get("state") == "completed":
                    break
                time.sleep(0.1)
            assert body.get("state") == "completed"
        finally:
            _stop(owner)
        thread.join(timeout=90)
    finally:
        _stop(stale)

    effects = Path(takeover_env["effects"])
    _assert_stale_zero_compute(effects)
    assert count_writer_effects(effects, role="owner", phase="ai_extend") == 2
    assert count_writer_effects(effects, role="owner", phase="submit") == 0


def test_generate_mock_takeover_zero_stale_submit(takeover_env: dict[str, Path | str]) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        stale_port = sock.getsockname()[1]
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock2:
        sock2.bind(("127.0.0.1", 0))
        owner_port = sock2.getsockname()[1]
    op_id = "generate-takeover"
    setup = _spawn(stale_port, _base_env(takeover_env, role="owner"))
    try:
        _wait_health(stale_port, setup)
        _http(stale_port, "POST", "/init", {"demo": True})
    finally:
        _stop(setup)
    time.sleep(2)

    stale = _spawn(
        stale_port,
        {
            **_base_env(takeover_env, role="stale"),
            "VINCI_TEST_DISABLE_HEARTBEAT": "1",
            "VINCI_TEST_SLEEP_DURING_EXECUTE_MS": "4000",
        },
    )

    def _stale_run() -> None:
        import httpx

        with httpx.Client(timeout=120) as client:
            client.post(
                f"http://127.0.0.1:{stale_port}/runs",
                json={
                    "skill": "@tryvinci/image-generate",
                    "inputs": {"prompt": "takeover fence"},
                    "max_cost": 1.0,
                },
                headers={"X-Vinci-Operation-Id": op_id},
            )

    try:
        _wait_health(stale_port, stale)
        thread = threading.Thread(target=_stale_run)
        thread.start()
        time.sleep(2.4)
        owner_home = takeover_env["durable"] / "home_generate"
        owner_home.mkdir(exist_ok=True)
        owner = _spawn(
            owner_port,
            {**_base_env(takeover_env, role="owner"), "VINCI_HOME": str(owner_home)},
        )
        try:
            _wait_health(owner_port, owner)
            journal = LocalDurableJournal(takeover_env["durable"] / "ledger.sqlite")
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

    effects = Path(takeover_env["effects"])
    _assert_stale_zero_compute(effects)
    assert count_writer_effects(effects, role="owner", phase="submit") == 1
    assert count_writer_effects(effects, role="owner", phase="completion") == 1


def test_between_nodes_sleep_after_node_stale_never_completes(
    takeover_env: dict[str, Path | str],
) -> None:
    """Barrier after node 0: stale may touch node 0 but must not commit output or submit."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        stale_port = sock.getsockname()[1]
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock2:
        sock2.bind(("127.0.0.1", 0))
        owner_port = sock2.getsockname()[1]
    op_id = "between-nodes-sleep-after"
    setup = _spawn(stale_port, _base_env(takeover_env, role="owner"))
    try:
        _wait_health(stale_port, setup)
        _http(stale_port, "POST", "/init", {"demo": True})
        asset_id = _upload(stale_port, "after-node-src")
    finally:
        _stop(setup)
    time.sleep(2)
    workflow = _two_adapt_workflow(asset_id)

    def _stale_run() -> None:
        import httpx

        with httpx.Client(timeout=120) as client:
            client.post(
                f"http://127.0.0.1:{stale_port}/runs",
                json={"inputs": {"media": asset_id}, "workflow": workflow},
                headers={"X-Vinci-Operation-Id": op_id},
            )

    stale = _spawn(
        stale_port,
        {
            **_base_env(takeover_env, role="stale"),
            "VINCI_TEST_DISABLE_HEARTBEAT": "1",
            "VINCI_TEST_SLEEP_AFTER_NODE_INDEX": "0",
            "VINCI_TEST_SLEEP_AFTER_NODE_MS": "4000",
        },
    )
    try:
        _wait_health(stale_port, stale)
        thread = threading.Thread(target=_stale_run)
        thread.start()
        time.sleep(2.4)
        owner_home = takeover_env["durable"] / "home_after_node"
        owner_home.mkdir(exist_ok=True)
        owner = _spawn(
            owner_port,
            {**_base_env(takeover_env, role="owner"), "VINCI_HOME": str(owner_home)},
        )
        try:
            _wait_health(owner_port, owner)
            journal = LocalDurableJournal(takeover_env["durable"] / "ledger.sqlite")
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

    effects = Path(takeover_env["effects"])
    assert count_writer_effects(effects, role="stale", phase="completion") == 0
    assert count_writer_effects(effects, role="stale", phase="submit") == 0
    assert count_writer_effects(effects, role="stale", phase="ledger_commit") == 0
    assert count_writer_effects(effects, role="stale", phase="run_state_completed") == 0
    assert count_writer_effects(effects, role="owner", phase="completion") == 1


def test_between_nodes_repeated_home_wipe_idempotent(takeover_env: dict[str, Path | str]) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    op_id = "wipe-resume-run"
    base = _base_env(takeover_env, role="owner")
    setup = _spawn(port, base)
    try:
        _wait_health(port, setup)
        _http(port, "POST", "/init", {"demo": True})
        asset_id = _upload(port, "wipe-src")
    finally:
        _stop(setup)
    time.sleep(2)
    workflow = _two_adapt_workflow(asset_id)

    killer = _spawn(port, {**base, "VINCI_TEST_EXIT_AFTER_ACK": "1"})
    try:
        _wait_health(port, killer)
        import httpx

        with httpx.Client(timeout=60) as client:
            client.post(
                f"http://127.0.0.1:{port}/runs",
                json={"inputs": {"media": asset_id}, "workflow": workflow},
                headers={"X-Vinci-Operation-Id": op_id},
            )
    except Exception:
        pass
    finally:
        try:
            killer.wait(timeout=30)
        except subprocess.TimeoutExpired:
            killer.kill()

    shutil.rmtree(takeover_env["home"])
    Path(takeover_env["effects"]).mkdir(parents=True, exist_ok=True)
    Path(takeover_env["home"]).mkdir()
    time.sleep(2)

    journal = LocalDurableJournal(takeover_env["durable"] / "ledger.sqlite")
    run_id = str(json.loads(journal.get_operation(op_id)["response_json"])["id"])

    for _ in range(2):
        proc = _spawn(port, base)
        try:
            _wait_health(port, proc)
            for _ in range(160):
                st, body = _http(port, "GET", f"/runs/{run_id}")
                if st == 200 and body.get("state") == "completed":
                    break
                time.sleep(0.1)
            assert body.get("state") == "completed"
        finally:
            _stop(proc)
        shutil.rmtree(takeover_env["home"])
        Path(takeover_env["home"]).mkdir()
        time.sleep(1)

    assert journal.get_operation(f"{op_id}:output")["status"] == "committed"
    effects = Path(takeover_env["effects"])
    assert count_writer_effects(effects, role="owner", phase="completion") == 1
    assert count_writer_effects(effects, role="stale", phase="completion") == 0
