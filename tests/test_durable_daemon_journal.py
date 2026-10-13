from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from vinci_storage.durable_paths import JOURNAL_WIRED_KINDS, MUTATION_RULES, classify_mutation


def test_all_inventory_mutations_wired() -> None:
    kinds = {kind for _m, _p, kind in MUTATION_RULES}
    assert kinds == JOURNAL_WIRED_KINDS
    assert classify_mutation("POST", "/runs") == "run_accept"
    assert classify_mutation("PUT", "/collab/sessions/abc") == "collab_put"


@pytest.fixture()
def journal_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("VINCI_DURABLE_JOURNAL", "local")
    monkeypatch.setenv("VINCI_HOME", str(tmp_path / "vinci"))
    from vinci_daemon.app import create_app

    return TestClient(create_app())


def test_settings_patch_ack_in_journal(journal_client: TestClient) -> None:
    journal_client.post("/init", json={"demo": True})
    res = journal_client.patch("/settings", json={"preference": "cheapest"})
    assert res.status_code == 200
    assert "operation_id" in res.json()


def test_asset_upload_ack_ledger(journal_client: TestClient) -> None:
    journal_client.post("/init", json={"demo": True})
    res = journal_client.post(
        "/assets",
        files={"file": ("t.txt", b"hello-ledger", "text/plain")},
    )
    assert res.status_code == 200
    body = res.json()
    assert body.get("operation_id")
    assert body.get("id")
