"""Axis Max Life pipeline: custom presets, batch exports, bundle, MCP, sheet sync."""

from __future__ import annotations

import io
import json
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from vinci_daemon.app import create_app
from vinci_media.adapt import png_dimensions
from vinci_provider_sdk.mock import png_scene
from vinci_runtime.engine import Engine

PRESETS = ("amazon_828x300", "inuxu_728x90", "jio_320x50")


class _MemorySheet:
    def __init__(self, rows: list[dict[str, object]], home: Path) -> None:
        self.rows = rows
        self.home = home
        self.writes: list[tuple[int, dict[str, str]]] = []
        self.baseline_batches: set[str] = set()

    def read_table(self, sheet_id: str, tab: str) -> list[dict[str, object]]:
        return [dict(row) for row in self.rows]

    def write_row(self, sheet_id: str, tab: str, row_number: int, fields: dict[str, str]) -> None:
        if fields.get("status") == "processing":
            current = {path.name for path in (self.home / "batches").glob("*.json")}
            created = current - self.baseline_batches
            if created:
                raise AssertionError(f"row claimed after a new batch existed: {sorted(created)}")
        self.writes.append((row_number, dict(fields)))
        for row in self.rows:
            if int(row["row_number"]) == row_number:
                row.update(fields)


def _png_server(payload: bytes) -> tuple[ThreadingHTTPServer, str]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            body = payload
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    return server, f"http://127.0.0.1:{port}/creative.png"


def _mcp(client: TestClient, name: str, arguments: dict[str, object]) -> dict[str, object]:
    res = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert "error" not in body, body
    parsed = json.loads(body["result"]["content"][0]["text"])
    assert isinstance(parsed, dict)
    return parsed


@pytest.fixture
def client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[TestClient, Engine, _MemorySheet]:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    monkeypatch.delenv("VINCI_ALLOW_LIVE_SPEND", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    engine = Engine(tmp_path)
    engine.init_home(demo=True)
    sheet = _MemorySheet([], tmp_path)
    return TestClient(create_app(engine, sheets_client=sheet)), engine, sheet


def test_axis_pipeline_e2e(
    client: tuple[TestClient, Engine, _MemorySheet], tmp_path: Path
) -> None:
    http, engine, sheet = client
    unconfigured = http.post("/integrations/gsheet/sync")
    assert unconfigured.status_code == 501
    assert "gsheet_id" in unconfigured.json()["detail"]

    created = http.post(
        "/presets",
        json={
            "label": "Axis lobby 320",
            "platform": "axis",
            "width": 320,
            "height": 100,
            "byte_cap": {"max_bytes": 80 * 1024, "op": "lte"},
            "safe_rect_margins_px": {"left": 8, "right": 8, "top": 4, "bottom": 4},
        },
    )
    assert created.status_code == 200, created.text
    custom = created.json()["preset"]
    custom_id = custom["id"]
    assert custom["source"] == "custom"
    assert http.delete(f"/presets/{custom_id}").status_code == 200
    again = http.post(
        "/presets",
        json={
            "id": custom_id,
            "label": "Axis lobby 320",
            "platform": "axis",
            "width": 320,
            "height": 100,
            "byte_cap": {"max_bytes": 80 * 1024, "op": "lte"},
            "safe_rect_margins_px": {"left": 8, "right": 8, "top": 4, "bottom": 4},
        },
    )
    assert again.status_code == 200, again.text

    listed = http.get("/presets").json()["presets"]
    by_id = {row["id"]: row for row in listed}
    assert by_id["instagram_feed"]["source"] == "generic"
    assert by_id["amazon_828x300"]["source"] == "partner"
    assert by_id[custom_id]["source"] == "custom"
    assert http.delete("/presets/amazon_828x300").status_code == 404
    assert http.delete("/presets/instagram_feed").status_code == 404
    bad = http.post("/presets", json={"label": "bad", "platform": "x", "width": 0, "height": 10})
    assert bad.status_code == 400
    assert (
        http.post(
            "/presets",
            json={
                "label": "huge",
                "platform": "x",
                "width": 32,
                "height": 32,
                "byte_cap": {"max_bytes": 50 * 1024 * 1024, "op": "lte"},
            },
        ).status_code
        == 400
    )

    preset_ids = [*PRESETS, custom_id]
    asset_ids: list[str] = []
    for seed in ("axis-a", "axis-b", "axis-c"):
        upload = http.post("/assets", files={"file": (f"{seed}.png", png_scene(seed), "image/png")})
        assert upload.status_code == 200, upload.text
        asset_ids.append(upload.json()["id"])
    assert len(set(asset_ids)) == 3

    batch = http.post(
        "/adapts/batch",
        json={
            "items": [
                {"asset_id": asset_id, "preset_ids": preset_ids} for asset_id in asset_ids
            ]
        },
    )
    assert batch.status_code == 200, batch.text
    batch_id = batch.json()["batch_id"]
    status = http.get(f"/adapts/batch/{batch_id}")
    assert status.status_code == 200
    items = status.json()["items"]
    assert len(items) == 3
    expected_names: set[str] = set()
    for item in items:
        assert item["status"] == "done", item
        assert item["error"] in (None, "")
        assert len(item["outputs"]) == 4
        for output in item["outputs"]:
            blob = http.get(f"/assets/{output['asset_id']}/file")
            assert blob.status_code == 200
            width, height = png_dimensions(blob.content)
            assert (width, height) == (output["width"], output["height"])
            assert output["dimensions"]["pass"] is True
            if output["preset_id"] == "amazon_828x300":
                assert output["byte_cap"]["pass"] is True
                assert output["byte_cap"]["actual_bytes"] <= 100 * 1024
                assert output["safe_area"]["applied"] is True
                assert output["safe_area"]["margins_px"]["left"] == 94
            if output["preset_id"] == custom_id:
                assert output["byte_cap"]["pass"] is True
                assert output["safe_area"]["applied"] is True
            if output["preset_id"] == "jio_320x50":
                assert output["byte_cap"] is None
            expected_names.add(
                f"{item['index']}_{output['preset_id']}_{output['width']}x{output['height']}.png"
            )
    bundle = http.get(f"/adapts/batch/{batch_id}/bundle.zip")
    assert bundle.status_code == 200
    assert bundle.headers["content-type"].startswith("application/zip")
    archive = zipfile.ZipFile(io.BytesIO(bundle.content))
    assert set(archive.namelist()) == expected_names
    assert len(expected_names) == 12

    tools = http.post("/mcp", json={"jsonrpc": "2.0", "id": 0, "method": "tools/list"})
    names = [row["name"] for row in tools.json()["result"]["tools"]]
    assert "vinci.presets_list" in names
    assert "vinci.adapts_run" in names
    assert "vinci.batch_status" in names
    presets = _mcp(http, "vinci.presets_list", {})
    assert any(row.get("id") == custom_id for row in presets["presets"])  # type: ignore[index]
    mcp_run = _mcp(
        http,
        "vinci.adapts_run",
        {"asset_id": asset_ids[0], "preset_ids": ["amazon_828x300", custom_id]},
    )
    mcp_status = _mcp(http, "vinci.batch_status", {"batch_id": mcp_run["batch_id"]})
    assert mcp_status["items"][0]["status"] == "done"  # type: ignore[index]

    server, url = _png_server(png_scene("sheet-row"))
    try:
        sheet.rows = [
            {
                "row_number": 2,
                "source_url": url,
                "presets": f"amazon_828x300,{custom_id}",
                "status": "",
                "output_links": "",
                "error": "",
            },
            {
                "row_number": 3,
                "source_url": url,
                "presets": "amazon_828x300",
                "status": "done",
                "output_links": "already",
                "error": "",
            },
            {
                "row_number": 4,
                "source_url": url,
                "presets": "amazon_828x300",
                "status": "processing",
                "output_links": "",
                "error": "",
            },
        ]
        patched = http.patch("/settings", json={"gsheet_id": "sheet-1", "gsheet_tab": "Exports"})
        assert patched.status_code == 200
        sheet.baseline_batches = {path.name for path in (sheet.home / "batches").glob("*.json")}
        synced = http.post("/integrations/gsheet/sync")
        assert synced.status_code == 200, synced.text
        body = synced.json()
        assert body["claimed"] == 1
        assert body["skipped"] == 2
        assert body["rows"][0]["status"] == "done"
        assert "/assets/" in body["rows"][0]["output_links"]
        assert sheet.rows[0]["status"] == "done"
        assert sheet.rows[1]["status"] == "done"
        assert sheet.rows[2]["status"] == "processing"
        processing_writes = [
            fields for _, fields in sheet.writes if fields.get("status") == "processing"
        ]
        assert processing_writes
        again_sync = http.post("/integrations/gsheet/sync")
        assert again_sync.status_code == 200
        assert again_sync.json()["claimed"] == 0
    finally:
        server.shutdown()
