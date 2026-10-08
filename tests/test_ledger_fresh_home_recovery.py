from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from vinci_storage.durable_journal import LocalDurableJournal


@pytest.fixture()
def durable_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    durable = tmp_path / "durable"
    durable.mkdir()
    home = tmp_path / "ephemeral-home"
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


def test_fresh_home_rebuilds_settings_and_asset_from_ledger(durable_env: dict[str, Path]) -> None:
    home = durable_env["home"]
    with _client() as c1:
        c1.post("/init", json={"demo": True})
        op_settings = "op-settings-recover"
        res = c1.patch(
            "/settings",
            json={"preference": "cheapest"},
            headers={"X-Vinci-Operation-Id": op_settings},
        )
        assert res.status_code == 200
        upload = c1.post(
            "/assets",
            files={"file": ("t.bin", b"ledger-bytes", "application/octet-stream")},
            headers={"X-Vinci-Operation-Id": "op-asset-recover"},
        )
        assert upload.status_code == 200
        asset_id = upload.json()["id"]
        assert (durable_env["durable"] / "cas").exists()

    shutil.rmtree(home)
    home.mkdir()

    with _client() as c2:
        settings = c2.get("/settings")
        assert settings.status_code == 200
        assert settings.json().get("preference") == "cheapest"
        assets = c2.get("/assets")
        assert assets.status_code == 200
        ids = {a["id"] for a in assets.json().get("assets", [])}
        assert asset_id in ids
        file_res = c2.get(f"/assets/{asset_id}/file")
        assert file_res.status_code == 200
        assert file_res.content == b"ledger-bytes"


def test_ledger_lists_committed_in_order(tmp_path: Path) -> None:
    journal = LocalDurableJournal(tmp_path / "j.sqlite")
    token = journal.acquire_writer()
    for idx, pref in enumerate(("cheapest", "fastest")):
        op = f"op-{idx}"
        journal.prepare_operation(
            token,
            op_id=op,
            kind="settings",
            path="/settings",
            blob_keys=[],
            payload={"preference": pref},
        )
        journal.commit_ack(
            token,
            kind="settings",
            path="/settings",
            blob_keys=[],
            payload={"preference": pref},
            response={"preference": pref},
            op_id=op,
        )
    rows = journal.list_committed_operations()
    assert len(rows) == 2
    assert json.loads(rows[-1]["response_json"])["preference"] == "fastest"
