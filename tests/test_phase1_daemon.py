from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from vinci_daemon.app import create_app
from vinci_mcp.server import TOOL_NAMES, handle_rpc
from vinci_runtime.engine import Engine


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    monkeypatch.delenv("VINCI_ALLOW_LIVE_SPEND", raising=False)
    engine = Engine(tmp_path)
    engine.init_home(demo=True)
    return TestClient(create_app(engine))


def test_healthz_and_handshake(client: TestClient) -> None:
    res = client.get("/healthz")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["protocol_version"] == "0.1.0"


def test_post_runs_workflow_path(client: TestClient) -> None:
    workflow = (
        Path(__file__).resolve().parents[1] / "skills" / "image-generate" / "workflow.yaml"
    )
    res = client.post(
        "/runs",
        json={"workflow_path": str(workflow), "inputs": {"prompt": "a red cube"}},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["state"] == "completed"
    assert body["outputs"]
    assert body["estimate"]["total"] == 0
    missing = client.post("/runs", json={"workflow_path": "/no/such/workflow.yaml"})
    assert missing.status_code == 400
    assert "not found" in missing.json()["detail"]


def test_post_runs_image_generate(client: TestClient) -> None:
    res = client.post(
        "/runs",
        json={"skill": "@tryvinci/image-generate", "inputs": {"prompt": "a red cube"}},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["state"] == "completed"
    assert body["outputs"]
    assert body["estimate"]["total"] == 0
    run_id = body["id"]
    got = client.get(f"/runs/{run_id}")
    assert got.json()["state"] == "completed"
    receipt_job = body["job_ids"][0]
    assert body["asset_uris"] == [f"vinci://assets/{body['outputs'][0]}"]
    assert body["job_uris"] == [f"vinci://jobs/{receipt_job}"]
    assert body["receipt_uris"] == [f"vinci://receipts/{receipt_job}"]
    job = client.get(f"/jobs/{receipt_job}").json()
    assert job["receipt"]["computed_cost"] == 0
    assert job["receipt"]["cached"] is False
    asset_id = body["outputs"][0]
    meta = client.get(f"/assets/{asset_id}")
    assert meta.status_code == 200
    assert meta.json()["uri"] == f"vinci://assets/{asset_id}"
    blob = client.get(f"/assets/{asset_id}/file")
    assert blob.status_code == 200
    assert blob.content.startswith(b"\x89PNG")
    width, height = struct.unpack(">II", blob.content[16:24])
    assert width == 960
    assert height == 540
    receipt = client.get(f"/receipts/{receipt_job}")
    assert receipt.status_code == 200
    assert receipt.json()["uri"] == f"vinci://receipts/{receipt_job}"
    assert receipt.json()["computed_cost"] == 0


def test_post_runs_video_generate(client: TestClient) -> None:
    res = client.post(
        "/runs",
        json={"skill": "@tryvinci/video-generate", "inputs": {"prompt": "a spinning cube"}},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["state"] == "completed"
    assert body["estimate"]["total"] == 0
    asset_id = body["outputs"][0]
    blob = client.get(f"/assets/{asset_id}/file")
    assert blob.status_code == 200
    assert blob.content[4:8] == b"ftyp"
    assert blob.headers.get("content-type") == "video/mp4"


def test_mcp_tools_and_image_generate(client: TestClient) -> None:
    listed = client.get("/mcp").json()
    assert listed["name"] == "vinci"
    assert listed["tools"] == list(TOOL_NAMES)
    init = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert init.json()["result"]["serverInfo"]["name"] == "vinci"
    tools = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = [t["name"] for t in tools.json()["result"]["tools"]]
    assert names == list(TOOL_NAMES)
    called = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "vinci.image_generate",
                "arguments": {"prompt": "mcp cube", "max_cost": 1},
            },
        },
    )
    text = called.json()["result"]["content"][0]["text"]
    assert "completed" in text
    assert "outputs" in text
    assert "vinci://assets/" in text
    assert "vinci://jobs/" in text
    assert "vinci://receipts/" in text


def test_mcp_authored_tools(client: TestClient) -> None:
    def call(name: str, arguments: dict) -> dict:
        res = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            },
        )
        assert res.status_code == 200
        body = res.json()
        assert "error" not in body, body
        return json.loads(body["result"]["content"][0]["text"])

    listed = client.post("/mcp", json={"jsonrpc": "2.0", "id": 0, "method": "tools/list"})
    names = [t["name"] for t in listed.json()["result"]["tools"]]
    assert names == list(TOOL_NAMES)

    models = call("vinci.models_list", {})
    assert any(row.get("id") == "mock:png:v1" for row in models["models"])

    skills = call("vinci.skills_search", {"query": "image-generate"})
    assert any(str(row.get("id", "")).endswith("image-generate") for row in skills["skills"])

    estimate = call(
        "vinci.cost_estimate",
        {"skill": "@tryvinci/image-generate", "inputs": {"prompt": "estimate only"}},
    )
    assert estimate["total"] == 0
    assert estimate["awaiting_reason"] is None

    image = call("vinci.image_generate", {"prompt": "authored mcp png", "max_cost": 1})
    assert image["state"] == "completed"
    asset_uri = image["asset_uris"][0]
    job_id = image["job_ids"][0]

    inspected = call("vinci.media_inspect", {"uri": asset_uri})
    assert inspected["id"] == asset_uri.removeprefix("vinci://assets/")
    assert inspected["uri"] == asset_uri

    job = call("vinci.jobs_get", {"job_id": job_id})
    assert job["id"] == job_id
    assert job["receipt"]["computed_cost"] == 0

    video = call("vinci.video_generate", {"prompt": "authored mcp mp4", "max_cost": 1})
    assert video["state"] == "completed"

    workflow = call(
        "vinci.workflow_run",
        {"skill": "@tryvinci/image-generate", "prompt": "authored mcp workflow", "max_cost": 1},
    )
    assert workflow["state"] == "completed"

    parked = call("vinci.image_generate", {"prompt": "authored mcp park", "max_cost": -0.01})
    assert parked["state"] == "awaiting_approval"
    cancelled = call("vinci.jobs_cancel", {"run_id": parked["id"]})
    assert cancelled["state"] == "cancelled"


def test_mcp_estimate_and_no_secret_leak(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    monkeypatch.setenv("MOCK_API_KEY", "mcp-secret-value")
    engine = Engine(tmp_path)
    engine.init_home(demo=True)
    result = handle_rpc(
        engine,
        {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {
                "name": "vinci.workflow_run",
                "arguments": {
                    "skill": "@tryvinci/video-generate",
                    "prompt": "say mcp-secret-value",
                    "max_cost": 1,
                },
            },
        },
    )
    assert result is not None
    blob = str(result)
    assert "mcp-secret-value" not in blob
    estimate = handle_rpc(
        engine,
        {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {
                "name": "vinci.cost_estimate",
                "arguments": {"skill": "@tryvinci/image-generate", "prompt": "hi"},
            },
        },
    )
    assert estimate is not None
    assert "result" in estimate


def test_catalog_refresh_http_does_not_mutate_bundled_json(
    client: TestClient, tmp_path: Path
) -> None:
    import vinci_core

    catalogs = Path(vinci_core.__file__).resolve().parent / "catalogs"
    before = {path.name: path.read_bytes() for path in catalogs.glob("*.json")}
    res = client.post("/catalog/refresh")
    assert res.status_code == 200
    body = res.json()
    assert body["note"].startswith("bundled snapshots")
    assert "diff" in body
    assert Path(body["path"]).name == "catalog.lock.json"
    after = {path.name: path.read_bytes() for path in catalogs.glob("*.json")}
    assert after == before


def test_http_awaiting_approval_then_approve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    monkeypatch.delenv("VINCI_ALLOW_LIVE_SPEND", raising=False)
    engine = Engine(tmp_path)
    engine.init_home(demo=True)
    engine.config.budget.require_approval_over = -0.01
    client = TestClient(create_app(engine))
    parked = client.post(
        "/runs",
        json={"skill": "@tryvinci/image-generate", "inputs": {"prompt": "park me"}},
    )
    assert parked.status_code == 200
    body = parked.json()
    assert body["state"] == "awaiting_approval"
    approved = client.post(f"/runs/{body['id']}/approve")
    assert approved.status_code == 200
    done = approved.json()
    assert done["state"] == "completed"
    assert done["estimate"]["total"] == 0


def test_root_redirects_to_studio(client: TestClient) -> None:
    res = client.get("/", follow_redirects=False)
    assert res.status_code in {302, 307}
    assert res.headers["location"].endswith("/studio")


def test_studio_pwa_manifest(client: TestClient) -> None:
    manifest = client.get("/studio/manifest.webmanifest")
    assert manifest.status_code == 200
    body = manifest.json()
    assert body["start_url"] == "/studio"
    icon = client.get("/studio/icon.svg")
    assert icon.status_code == 200
    assert "svg" in icon.headers.get("content-type", "")


def test_byok_secret_never_echoed_and_settings(client: TestClient) -> None:
    res = client.post(
        "/providers",
        json={"id": "wavespeed", "secret": "file-stored-provider-key"},
    )
    assert res.status_code == 200, res.text
    assert "file-stored-provider-key" not in res.text
    body = res.json()
    assert body["ref"] in {"file", "keychain"}
    doctor = client.get("/doctor").json()
    assert doctor["providers"]["wavespeed"]["configured"] is True
    assert doctor["preference"] == "cheapest"
    patched = client.patch("/settings", json={"preference": "quality", "monthly_cap_usd": 9})
    assert patched.status_code == 200
    assert patched.json()["preference"] == "quality"
    assert patched.json()["budget"]["monthly_cap_usd"] == 9
    bad = client.patch("/settings", json={"preference": "not-a-route"})
    assert bad.status_code == 400
