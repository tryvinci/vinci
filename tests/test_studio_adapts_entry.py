from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from vinci_daemon.app import create_app
from vinci_provider_sdk.mock import PNG_SWATCH
from vinci_runtime.engine import Engine


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    monkeypatch.delenv("VINCI_ALLOW_LIVE_SPEND", raising=False)
    engine = Engine(tmp_path)
    engine.init_home(demo=True)
    return TestClient(create_app(engine))


def test_studio_adapts_ui_strings(client: TestClient) -> None:
    page = client.get("/studio")
    assert page.status_code == 200
    body = page.text
    assert "adapt-panel" in body
    assert "Adapts" in body
    assert "Image › Adapts presets" in body
    assert "Partner presets" in body
    assert "Axis" not in body
    assert "axis" not in body.lower()
    assert "fit_pad_crop" in body or "fit / pad / crop" in body.lower()
    assert "adapt/presets" in body or "/adapt/estimate" in body
    assert "Image › Adapts" in body
    assert "partner" in body


def test_adapt_route_reachable_with_mock_engine(client: TestClient) -> None:
    presets = client.get("/adapt/presets").json()["presets"]
    partner_ids = {row["id"] for row in presets if row.get("spec_kind") == "client_partner"}
    assert "amazon_828x300" in partner_ids

    upload = client.post(
        "/assets",
        files={"file": ("creative.png", PNG_SWATCH, "image/png")},
    )
    assert upload.status_code == 200
    asset_id = upload.json()["id"]

    estimate = client.post(
        "/adapt/estimate",
        json={
            "source_asset": asset_id,
            "targets": [{"preset_id": "amazon_828x300"}, {"preset_id": "inuxu_1200x720"}],
            "layout": "fit_pad_crop",
        },
    )
    assert estimate.status_code == 200
    est_body = estimate.json()
    assert est_body["total"] == 0.0
    assert "ffmpeg" in (est_body.get("note") or "").lower()

    run = client.post(
        "/adapt/run",
        json={
            "source_asset": asset_id,
            "targets": [{"preset_id": "amazon_828x300"}, {"preset_id": "inuxu_1200x720"}],
            "layout": "fit_pad_crop",
            "fit_mode": "pad",
        },
    )
    assert run.status_code == 200
    run_body = run.json()
    assert len(run_body["digests"]) == 2
    assert run_body["estimate"]["total"] == 0.0
    for row in run_body.get("outputs") or []:
        validation = row.get("validation") or {}
        assert validation.get("spec_kind") == "client_partner"
