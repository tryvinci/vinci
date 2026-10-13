from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from vinci_provider_sdk.mock import PNG_SWATCH
from vinci_storage.durable_journal import LocalDurableJournal

ROOT = Path(__file__).resolve().parent


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


def test_adapt_batch_route_replay_restores_batch_json_and_status(
    durable_env: dict[str, Path],
) -> None:
    with _client() as client:
        client.post("/init", json={"demo": True})
        upload = client.post(
            "/assets",
            files={"file": ("src.png", PNG_SWATCH, "image/png")},
            headers={"X-Vinci-Operation-Id": "batch-src"},
        )
        source_id = upload.json()["id"]
        batch = client.post(
            "/adapts/batch",
            json={
                "items": [{"asset_id": source_id, "preset_ids": ["instagram_feed"]}],
                "fit_mode": "pad",
                "layout": "fit_pad_crop",
            },
            headers={"X-Vinci-Operation-Id": "batch-route-1"},
        )
        assert batch.status_code == 200, batch.text
        batch_id = batch.json()["batch_id"]
        for _ in range(120):
            status = client.get(f"/adapts/batch/{batch_id}").json()
            if status["items"][0].get("status") == "done":
                break
            time.sleep(0.05)
        assert status["items"][0]["status"] == "done"

    journal = LocalDurableJournal(durable_env["durable"] / "ledger.sqlite")
    bundle_row = journal.get_operation("batch-route-1:batch_bundle")
    assert bundle_row is not None

    shutil.rmtree(durable_env["home"])
    durable_env["home"].mkdir()

    with _client() as client2:
        status2 = client2.get(f"/adapts/batch/{batch_id}").json()
        assert status2["items"][0]["status"] == "done"
        assert (durable_env["home"] / "batches" / f"{batch_id}.json").is_file()


def test_mcp_jobs_cancel_replay_preserves_cancelled_run(durable_env: dict[str, Path]) -> None:
    with _client() as client:
        client.post("/init", json={"demo": True})
        parked = client.post(
            "/runs",
            json={
                "skill": "@tryvinci/image-generate",
                "inputs": {"prompt": "cancel replay"},
                "max_cost": -0.01,
            },
            headers={"X-Vinci-Operation-Id": "park-run"},
        )
        assert parked.status_code == 200
        run_id = parked.json()["id"]
        cancelled = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 9,
                "method": "tools/call",
                "params": {
                    "name": "vinci.jobs_cancel",
                    "arguments": {"run_id": run_id},
                },
            },
            headers={"X-Vinci-Operation-Id": "mcp-cancel-1"},
        )
        assert cancelled.status_code == 200
        envelope = cancelled.json()
        assert envelope.get("ledger_replay", {}).get("kind") == "run_cancel"

    shutil.rmtree(durable_env["home"])
    durable_env["home"].mkdir()

    with _client() as client2:
        run = client2.get(f"/runs/{run_id}").json()
        assert run.get("state") == "cancelled"


def test_mcp_deferred_run_stable_id_no_duplicate_on_cached_replay(
    durable_env: dict[str, Path],
) -> None:
    journal_path = durable_env["durable"] / "ledger.sqlite"
    with _client() as client:
        client.post("/init", json={"demo": True})
        op_id = "mcp-stable-dedupe"
        msg = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "vinci.image_generate",
                "arguments": {"prompt": "stable op id", "max_cost": 1},
            },
        }
        first = client.post(
            "/mcp",
            json=msg,
            headers={"X-Vinci-Operation-Id": op_id},
        )
        assert first.status_code == 200
        text = first.json()["result"]["content"][0]["text"]
        run_a = json.loads(text)
        second = client.post(
            "/mcp",
            json=msg,
            headers={"X-Vinci-Operation-Id": op_id},
        )
        assert second.status_code == 200
        run_b = json.loads(second.json()["result"]["content"][0]["text"])
        assert run_a["id"] == run_b["id"]

    journal = LocalDurableJournal(journal_path)
    mcp_ops = [r for r in journal.iter_committed_operations() if r["kind"] == "mcp_rpc"]
    assert len(mcp_ops) == 1
