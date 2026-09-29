from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from http.server import ThreadingHTTPServer
from pathlib import Path
from struct import unpack

import pytest
from fastapi.testclient import TestClient
from vinci_daemon.app import create_app
from vinci_mcp.adapter import McpProvider
from vinci_mcp.mock_server import Handler
from vinci_media.ops import make_fixture_video
from vinci_protocol.enums import Capability
from vinci_protocol.models import JobRequest, ModelSpec, WorkflowSpec
from vinci_provider_sdk.catalog_provider import LiveSpendDisabled
from vinci_runtime.comfy import import_comfy
from vinci_runtime.engine import Engine
from vinci_storage.cas import ContentAddressedStore

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SKILL_A = FIXTURES / "skills" / "stamp-text"
SKILL_B = FIXTURES / "skills" / "stamp-video"
COMFY = FIXTURES / "comfy" / "text2img.json"


@pytest.fixture
def engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Engine:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    monkeypatch.delenv("VINCI_ALLOW_LIVE_SPEND", raising=False)
    eng = Engine(tmp_path)
    eng.init_home(demo=True)
    return eng


def test_second_skill_installs(engine: Engine) -> None:
    before = {s.id for s in engine.skills.list_skills()}
    assert "@example/stamp-text" not in before
    assert "@example/stamp-video" not in before
    first = engine.install_skill(SKILL_A)
    second = engine.install_skill(SKILL_B)
    assert first["id"] == "@example/stamp-text"
    assert second["id"] == "@example/stamp-video"
    ids = {s.id for s in engine.skills.list_skills()}
    assert "@example/stamp-text" in ids
    assert "@example/stamp-video" in ids
    run = engine.start_run("@example/stamp-text", {"prompt": "installed cube"})
    assert run["state"] == "completed"
    assert run["estimate"]["total"] == 0


def test_timeline_render_local(engine: Engine, tmp_path: Path) -> None:
    a = make_fixture_video(tmp_path / "a.mp4", duration=1.0)
    b = make_fixture_video(tmp_path / "b.mp4", duration=1.0)
    asset_a = engine.ingest_bytes(a.read_bytes(), mime="video/mp4", filename="a.mp4")
    asset_b = engine.ingest_bytes(b.read_bytes(), mime="video/mp4", filename="b.mp4")
    run = engine.start_run(
        None,
        {},
        workflow=WorkflowSpec.model_validate(
            {
                "id": "studio-timeline",
                "version": "0.1.0",
                "nodes": [
                    {
                        "id": "render",
                        "type": "media",
                        "params": {
                            "op": "render_timeline",
                            "clips": [
                                {"asset_id": asset_a.id, "start": 0, "end": 0.6},
                                {"asset_id": asset_b.id},
                            ],
                        },
                    }
                ],
                "edges": [],
            }
        ),
    )
    assert run["state"] == "completed"
    assert run["estimate"]["total"] == 0
    assert run["outputs"]


def test_comfy_import_and_run(engine: Engine) -> None:
    graph = json.loads(COMFY.read_text(encoding="utf-8"))
    spec = import_comfy(graph)
    assert spec.nodes[0].params["prompt"] == "a stamped red cube"
    run = engine.start_run(None, {}, workflow=spec)
    assert run["state"] == "completed"
    assert run["estimate"]["total"] == 0


def test_engine_registers_mcp_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    monkeypatch.setenv("MCP_API_KEY", "mcp-secret-value")
    monkeypatch.delenv("VINCI_ALLOW_LIVE_SPEND", raising=False)
    spec = ModelSpec(
        id="mcp:png:v1",
        display_name="MCP PNG",
        provider="mcp",
        capabilities=[Capability.T2I],
        pricing={
            "unit": "image",
            "amount": 0.0,
            "currency": "USD",
            "snapshot_at": datetime(2026, 8, 27, tzinfo=UTC),
        },
        secret_names=["MCP_API_KEY"],
    )

    def fake_call(self: object, method: str, params: dict[str, object]) -> dict[str, object]:
        del method, params
        return {"models": [spec.model_dump(mode="json")]}

    monkeypatch.setattr("vinci_mcp.adapter.HttpMcpTransport.call", fake_call)
    eng = Engine(tmp_path)
    eng.init_home(demo=False)
    added = eng.add_provider(
        "mcp", from_env="MCP_API_KEY", url="http://127.0.0.1:9/mcp"
    )
    assert added["id"] == "mcp"
    assert added["url"] == "http://127.0.0.1:9/mcp"
    assert "mcp" in eng.providers
    models = eng.catalog().models
    assert any(model.id == "mcp:png:v1" for model in models)
    client = TestClient(create_app(eng))
    listed = client.get("/providers")
    assert listed.status_code == 200
    assert "mcp" in listed.json()


def test_daemon_mcp_provider_requires_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    monkeypatch.delenv("VINCI_ALLOW_LIVE_SPEND", raising=False)
    eng = Engine(tmp_path)
    eng.init_home(demo=True)
    client = TestClient(create_app(eng))
    missing = client.post("/providers", json={"id": "mcp"})
    assert missing.status_code == 400
    assert "url" in missing.json()["detail"]


def test_mcp_adapter_estimate_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VINCI_ALLOW_LIVE_SPEND", raising=False)
    spec = ModelSpec(
        id="mcp:png:v1",
        display_name="MCP PNG",
        provider="mcp",
        capabilities=[Capability.T2I],
        pricing={
            "unit": "image",
            "amount": 0.0,
            "currency": "USD",
            "snapshot_at": datetime(2026, 8, 27, tzinfo=UTC),
        },
        secret_names=["MCP_API_KEY"],
    )

    class Transport:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def call(self, method: str, params: dict[str, object]) -> dict[str, object]:
            self.calls.append((method, params))
            return {"models": [spec.model_dump(mode="json")]}

    transport = Transport()
    provider = McpProvider(transport, api_key="mcp-secret-value")
    req = JobRequest(capability=Capability.T2I, inputs={"prompt": "mcp cube"})
    estimate = provider.estimate(req)
    assert estimate.amount == 0
    assert estimate.model_id == "mcp:png:v1"
    with pytest.raises(LiveSpendDisabled):
        provider.submit(req)
    blob = json.dumps(transport.calls)
    assert "mcp-secret-value" not in blob


def test_mcp_adapter_remote_requires_live_spend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("VINCI_ALLOW_LIVE_SPEND", raising=False)
    spec = ModelSpec(
        id="mcp:png:v1",
        display_name="MCP PNG",
        provider="mcp",
        capabilities=[Capability.T2I],
        pricing={
            "unit": "image",
            "amount": 0.0,
            "currency": "USD",
            "snapshot_at": datetime(2026, 8, 27, tzinfo=UTC),
        },
        secret_names=["MCP_API_KEY"],
    )

    class Transport:
        url = "https://example.invalid/mcp"

        def call(self, method: str, params: dict[str, object]) -> dict[str, object]:
            del method, params
            return {"models": [spec.model_dump(mode="json")]}

    provider = McpProvider(
        Transport(),
        api_key="mcp-secret-value",
        cas=ContentAddressedStore(tmp_path / "cas"),
    )
    req = JobRequest(capability=Capability.T2I, inputs={"prompt": "remote cube"})
    provider.estimate(req)
    with pytest.raises(LiveSpendDisabled):
        provider.submit(req)


def test_mcp_loopback_http_submit_zero_cost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    monkeypatch.setenv("MCP_API_KEY", "mcp-secret-value")
    monkeypatch.delenv("VINCI_ALLOW_LIVE_SPEND", raising=False)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = int(server.server_address[1])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        eng = Engine(tmp_path)
        eng.init_home(demo=True)
        added = eng.add_provider(
            "mcp", from_env="MCP_API_KEY", url=f"http://127.0.0.1:{port}/mcp"
        )
        assert added["id"] == "mcp"
        assert "mcp" in eng.enabled_provider_ids()
        run = eng.start_run(
            None,
            {"prompt": "mcp loopback cube"},
            workflow=WorkflowSpec.model_validate(
                {
                    "id": "mcp-png",
                    "version": "0.1.0",
                    "nodes": [
                        {
                            "id": "generate",
                            "type": "generate",
                            "capability": "t2i",
                            "model_id": "mcp:png:v1",
                            "params": {"prompt": "mcp loopback cube"},
                        }
                    ],
                    "edges": [],
                }
            ),
        )
        assert run["state"] == "completed"
        assert run["estimate"]["total"] == 0
        assert run["estimate"]["nodes"][0]["model_id"] == "mcp:png:v1"
        digest = run["outputs"][0]
        blob = eng.cas.get(digest)
        width, height = unpack(">II", blob[16:24])
        assert (width, height) == (960, 540)
        dumped = json.dumps(run, default=str)
        assert "mcp-secret-value" not in dumped
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_mcp_loopback_http_submit_video_zero_cost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    monkeypatch.setenv("MCP_API_KEY", "mcp-secret-value")
    monkeypatch.delenv("VINCI_ALLOW_LIVE_SPEND", raising=False)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = int(server.server_address[1])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        eng = Engine(tmp_path)
        eng.init_home(demo=True)
        added = eng.add_provider(
            "mcp", from_env="MCP_API_KEY", url=f"http://127.0.0.1:{port}/mcp"
        )
        assert added["id"] == "mcp"
        run = eng.start_run(
            None,
            {"prompt": "mcp loopback clip"},
            workflow=WorkflowSpec.model_validate(
                {
                    "id": "mcp-mp4",
                    "version": "0.1.0",
                    "nodes": [
                        {
                            "id": "generate",
                            "type": "generate",
                            "capability": "t2v",
                            "model_id": "mcp:mp4:v1",
                            "params": {"prompt": "mcp loopback clip"},
                        }
                    ],
                    "edges": [],
                }
            ),
        )
        assert run["state"] == "completed"
        assert run["estimate"]["total"] == 0
        assert run["estimate"]["nodes"][0]["model_id"] == "mcp:mp4:v1"
        blob = eng.cas.get(run["outputs"][0])
        assert blob[4:8] == b"ftyp"
        dumped = json.dumps(run, default=str)
        assert "mcp-secret-value" not in dumped
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_mcp_adapter_rejects_non_av_submit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("VINCI_ALLOW_LIVE_SPEND", raising=False)
    spec = ModelSpec(
        id="mcp:tts:v1",
        display_name="MCP TTS",
        provider="mcp",
        capabilities=[Capability.TTS],
        pricing={
            "unit": "call",
            "amount": 0.0,
            "currency": "USD",
            "snapshot_at": datetime(2026, 8, 27, tzinfo=UTC),
        },
        secret_names=["MCP_API_KEY"],
    )

    class Transport:
        url = "http://127.0.0.1:9/mcp"

        def call(self, method: str, params: dict[str, object]) -> dict[str, object]:
            del method, params
            return {"models": [spec.model_dump(mode="json")]}

    provider = McpProvider(
        Transport(),
        api_key="mcp-secret-value",
        cas=ContentAddressedStore(tmp_path / "cas"),
    )
    req = JobRequest(capability=Capability.TTS, inputs={"prompt": "say hi"})
    provider.estimate(req)
    with pytest.raises(ValueError, match="image and video"):
        provider.submit(req)


def test_daemon_install_and_comfy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    monkeypatch.delenv("VINCI_ALLOW_LIVE_SPEND", raising=False)
    eng = Engine(tmp_path)
    eng.init_home(demo=True)
    client = TestClient(create_app(eng))
    first = client.post("/skills/install", json={"path": str(SKILL_A)})
    assert first.status_code == 200, first.text
    second = client.post("/skills/install", json={"path": str(SKILL_B)})
    assert second.status_code == 200, second.text
    ids = {s["id"] for s in client.get("/skills").json()["skills"]}
    assert "@example/stamp-text" in ids
    assert "@example/stamp-video" in ids
    graph = json.loads(COMFY.read_text(encoding="utf-8"))
    imported = client.post("/workflows/import/comfy", json={"graph": graph, "run": True})
    assert imported.status_code == 200, imported.text
    assert imported.json()["state"] == "completed"
    page = client.get("/studio")
    assert "Timeline" in page.text
