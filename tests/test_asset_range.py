from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from vinci_daemon.app import create_app
from vinci_runtime.engine import Engine


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    monkeypatch.setenv("VINCI_SKIP_HOME_LOCK", "1")
    engine = Engine(tmp_path)
    engine.init_home(demo=True)
    return TestClient(create_app(engine))


def test_asset_file_range_206(client: TestClient) -> None:
    res = client.post(
        "/runs",
        json={"skill": "@tryvinci/image-generate", "inputs": {"prompt": "cube"}},
    )
    assert res.status_code == 200
    asset_id = res.json()["outputs"][0]
    full = client.get(f"/assets/{asset_id}/file")
    assert full.status_code == 200
    assert full.headers.get("accept-ranges") == "bytes"
    ranged = client.get(f"/assets/{asset_id}/file", headers={"Range": "bytes=0-3"})
    assert ranged.status_code == 206
    assert ranged.headers.get("content-range", "").startswith("bytes 0-3/")
