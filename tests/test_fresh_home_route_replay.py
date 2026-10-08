from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from vinci_storage.durable_journal import LocalDurableJournal

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures"
SKILL_A = FIXTURES / "skills" / "stamp-text"


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


def test_skill_install_route_replay_restores_skill_tree(durable_env: dict[str, Path]) -> None:
    with _client() as client:
        client.post("/init", json={"demo": True})
        installed = client.post(
            "/skills/install",
            json={"path": str(SKILL_A)},
            headers={"X-Vinci-Operation-Id": "skill-route-1"},
        )
        assert installed.status_code == 200, installed.text
        skill_id = installed.json()["id"]
        assert skill_id == "@example/stamp-text"
        listed = client.get("/skills").json()["skills"]
        assert any(s["id"] == skill_id for s in listed)

    shutil.rmtree(durable_env["home"])
    durable_env["home"].mkdir()

    with _client() as client2:
        skills = client2.get("/skills").json()["skills"]
        assert any(s["id"] == "@example/stamp-text" for s in skills)


def test_mcp_image_generate_envelope_replay_restores_jobs(
    durable_env: dict[str, Path],
) -> None:
    with _client() as client:
        client.post("/init", json={"demo": True})
        called = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "vinci.image_generate",
                    "arguments": {"prompt": "fresh home mcp cube", "max_cost": 1},
                },
            },
            headers={"X-Vinci-Operation-Id": "mcp-route-1"},
        )
        assert called.status_code == 200, called.text
        envelope = called.json()
        assert envelope.get("jsonrpc") == "2.0"
        assert "ledger_replay" in envelope
        assert envelope["ledger_replay"].get("kind") == "run"
        text = envelope["result"]["content"][0]["text"]
        run_body = json.loads(text)
        run_id = run_body["id"]
        for _ in range(90):
            body = client.get(f"/runs/{run_id}").json()
            if body.get("state") == "completed" and body.get("job_ids"):
                job_id = body["job_ids"][0]
                break
            time.sleep(0.05)
        else:
            raise AssertionError("run did not complete")

    journal = LocalDurableJournal(durable_env["durable"] / "ledger.sqlite")
    mcp_rows = [
        r
        for r in journal.iter_committed_operations(page_size=100)
        if r.get("kind") == "mcp_rpc"
    ]
    assert mcp_rows
    parent_op = str(mcp_rows[-1]["op_id"])
    bundle_row = journal.get_operation(f"{parent_op}:mcp_bundle")
    assert bundle_row is not None
    bundle = json.loads(bundle_row["response_json"])
    assert bundle.get("kind") == "run"

    shutil.rmtree(durable_env["home"])
    durable_env["home"].mkdir()

    with _client() as client2:
        jobs = client2.get("/jobs").json()["jobs"]
        assert any(j["id"] == job_id for j in jobs)
        receipt = client2.get(f"/receipts/{job_id}")
        assert receipt.status_code == 200
