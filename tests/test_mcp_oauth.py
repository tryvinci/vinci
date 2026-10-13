"""OAuth sign-in for MCP connectors. Loopback only; no provider spend."""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

import pytest
from fastapi.testclient import TestClient
from vinci_daemon.app import create_app
from vinci_mcp.adapter import McpProvider
from vinci_mcp.connectors import parse_generate, parse_status
from vinci_mcp.oauth import OAuthError, _require_oauth_endpoint, access_token, clear_pending
from vinci_protocol.enums import Capability
from vinci_protocol.models import JobRequest
from vinci_runtime.engine import Engine
from vinci_storage.cas import ContentAddressedStore

from loopback_oauth_server import OAuthServer

PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@pytest.fixture
def oauth_server() -> Iterator[OAuthServer]:
    server = OAuthServer()
    server.start()
    clear_pending()
    yield server
    clear_pending()
    server.stop()


class _StopRedirect(HTTPRedirectHandler):
    def redirect_request(  # type: ignore[override]
        self,
        req: Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        del req, fp, code, msg
        raise HTTPError(newurl, 302, "redirect", headers, None)  # type: ignore[arg-type]


def _redirect_target(authorize_url: str) -> str:
    opener = build_opener(_StopRedirect)
    try:
        opener.open(authorize_url, timeout=5)
    except HTTPError as exc:
        if exc.code == 302:
            return exc.url
        raise
    raise AssertionError("authorize did not redirect")


def test_oauth_pkce_callback_refresh_and_redaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, oauth_server: OAuthServer
) -> None:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    monkeypatch.delenv("VINCI_ALLOW_LIVE_SPEND", raising=False)
    monkeypatch.setenv("VINCI_BRIDGE_TOKEN", "bridge-test-token")
    eng = Engine(tmp_path)
    eng.init_home(demo=True)
    client = TestClient(create_app(eng))
    auth = {"Authorization": "Bearer bridge-test-token"}
    added = client.post(
        "/providers",
        json={"id": "mcp_magnific", "url": f"{oauth_server.origin}/mcp"},
        headers=auth,
    )
    assert added.status_code == 200, added.text
    started = client.post("/providers/mcp_magnific/oauth", headers=auth)
    assert started.status_code == 200, started.text
    body = started.json()
    assert body["mode"] == "oauth"
    assert "code_challenge_method=S256" in body["authorize_url"]
    landed = _redirect_target(body["authorize_url"])
    assert "code=" in landed and "state=" in landed
    query = landed.split("?", 1)[1]
    callback = client.get(f"/providers/oauth/callback?{query}")
    assert callback.status_code == 200
    assert "Connected" in callback.text
    assert "access-" not in callback.text
    blocked = client.get("/providers")
    assert blocked.status_code == 401
    authed = client.get("/providers", headers=auth)
    assert authed.status_code == 200
    row = authed.json()["mcp_magnific"]
    assert row["auth_state"] == "connected"
    config = (tmp_path / "config.toml").read_text(encoding="utf-8")
    assert "access-" not in config
    token = access_token(eng.resolver, "mcp_magnific")
    assert token and token.startswith("access-")
    eng._emit("oauth.check", payload={"note": token})
    events = eng.store.list_events()
    assert token not in json.dumps(events)
    again = client.get(f"/providers/oauth/callback?{query}")
    assert again.status_code == 400
    assert "reused" in again.text or "unknown" in again.text
    stored = json.loads(eng.resolver.resolve("MCP_OAUTH_MAGNIFIC") or "{}")
    stored["expires_at"] = 0
    eng.resolver.put("MCP_OAUTH_MAGNIFIC", json.dumps(stored))
    refreshed = access_token(eng.resolver, "mcp_magnific")
    assert refreshed and refreshed != token

    def fail_refresh(url: str, body: dict[str, str], *, allow_loopback: bool) -> dict[str, str]:
        del url, body, allow_loopback
        raise OAuthError("revoked")

    monkeypatch.setattr("vinci_mcp.oauth._token_request", fail_refresh)
    stored = json.loads(eng.resolver.resolve("MCP_OAUTH_MAGNIFIC") or "{}")
    stored["expires_at"] = 0
    eng.resolver.put("MCP_OAUTH_MAGNIFIC", json.dumps(stored))
    assert access_token(eng.resolver, "mcp_magnific") is None
    assert json.loads(eng.resolver.resolve("MCP_OAUTH_MAGNIFIC") or "{}")["needs_reconnect"] is True
    removed = client.post("/providers/mcp_magnific/disconnect", headers=auth)
    assert removed.status_code == 200, removed.text
    assert eng.resolver.resolve("MCP_OAUTH_MAGNIFIC") is None
    still = client.get("/providers", headers=auth).json()["mcp_magnific"]
    assert still["url"] == f"{oauth_server.origin}/mcp"


def test_oauth_state_expires(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, oauth_server: OAuthServer
) -> None:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    monkeypatch.setattr("vinci_mcp.oauth.STATE_TTL_SECONDS", -1)
    eng = Engine(tmp_path)
    eng.init_home(demo=True)
    client = TestClient(create_app(eng))
    client.post("/providers", json={"id": "mcp_higgsfield", "url": f"{oauth_server.origin}/mcp"})
    started = client.post("/providers/mcp_higgsfield/oauth")
    assert started.status_code == 200, started.text
    landed = _redirect_target(started.json()["authorize_url"])
    query = landed.split("?", 1)[1]
    callback = client.get(f"/providers/oauth/callback?{query}")
    assert callback.status_code == 400
    assert "expired" in callback.text


def test_denied_oauth_state_cannot_be_exchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, oauth_server: OAuthServer
) -> None:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    eng = Engine(tmp_path)
    eng.init_home(demo=True)
    client = TestClient(create_app(eng))
    client.post("/providers", json={"id": "mcp_magnific", "url": f"{oauth_server.origin}/mcp"})
    started = client.post("/providers/mcp_magnific/oauth")
    assert started.status_code == 200, started.text
    landed = _redirect_target(started.json()["authorize_url"])
    query = landed.split("?", 1)[1]
    denied = client.get(f"/providers/oauth/callback?error=access_denied&{query}")
    assert denied.status_code == 400
    assert "denied" in denied.text
    reused = client.get(f"/providers/oauth/callback?{query}")
    assert reused.status_code == 400
    assert "unknown" in reused.text or "reused" in reused.text


def test_disconnect_drops_pending_oauth_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, oauth_server: OAuthServer
) -> None:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    eng = Engine(tmp_path)
    eng.init_home(demo=True)
    client = TestClient(create_app(eng))
    client.post("/providers", json={"id": "mcp_magnific", "url": f"{oauth_server.origin}/mcp"})
    started = client.post("/providers/mcp_magnific/oauth")
    assert started.status_code == 200, started.text
    landed = _redirect_target(started.json()["authorize_url"])
    query = landed.split("?", 1)[1]
    dropped = client.post("/providers/mcp_magnific/disconnect")
    assert dropped.status_code == 200, dropped.text
    callback = client.get(f"/providers/oauth/callback?{query}")
    assert callback.status_code == 400
    assert "unknown" in callback.text or "reused" in callback.text


def test_credit_connector_receipt_is_not_usd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    monkeypatch.delenv("VINCI_ALLOW_LIVE_SPEND", raising=False)

    def fake_call(self: object, method: str, params: dict[str, object]) -> dict[str, object]:
        del self
        if method == "tools/list":
            return {"tools": [{"name": "images_generate"}, {"name": "creation_status"}]}
        name = params.get("name")
        if name == "images_generate":
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {"id": "c1", "status": "completed", "b64": PNG_B64}
                        ),
                    }
                ]
            }
        raise AssertionError(method)

    monkeypatch.setattr("vinci_mcp.adapter.HttpMcpTransport.call", fake_call)
    eng = Engine(tmp_path)
    eng.init_home(demo=True)
    client = TestClient(create_app(eng))
    added = client.post(
        "/providers",
        json={
            "id": "mcp_magnific",
            "url": "http://127.0.0.1:9/mcp",
            "secret": "pasted-bearer",
        },
    )
    assert added.status_code == 200, added.text
    run = client.post(
        "/runs",
        json={
            "skill": "@tryvinci/image-generate",
            "inputs": {"prompt": "a red cube"},
            "model_id": "mcp_magnific:images_generate",
        },
    )
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["state"] == "completed"
    assert body["estimate"]["currency"] == "USD"
    assert body["estimate"]["total"] == 0
    assert body["estimate"]["nodes"][0]["currency"] == "credits"
    blob = base64.b64decode(PNG_B64)
    assert eng.cas.exists(body["outputs"][0])
    assert eng.cas.get(body["outputs"][0]) == blob
    job_id = body["job_ids"][0]
    job = eng.store.get_job(job_id)
    assert job is not None and job.receipt is not None
    receipt = job.receipt
    assert receipt.currency == "credits"
    assert receipt.computed_cost == 1.0
    assert eng.store.month_spend() == 0


def test_connector_submit_via_provider(tmp_path: Path) -> None:
    calls: list[str] = []

    class Transport:
        url = "http://127.0.0.1:9/mcp"

        def bearer(self) -> str:
            return "loopback-bearer"

        def call(self, method: str, params: dict[str, object]) -> dict[str, object]:
            calls.append(method + ":" + str(params.get("name") or ""))
            if method == "tools/list":
                return {"tools": [{"name": "generate_image"}, {"name": "get_generation"}]}
            if params.get("name") == "generate_image":
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps({"id": "h1", "status": "running"}),
                        }
                    ]
                }
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {"id": "h1", "status": "completed", "b64": PNG_B64}
                        ),
                    }
                ]
            }

    cas = ContentAddressedStore(tmp_path / "cas")
    provider = McpProvider(Transport(), cas=cas, provider_id="mcp_higgsfield")  # type: ignore[arg-type]
    models = provider.catalog()
    assert models and models[0].pricing.currency == "credits"
    req = JobRequest(
        capability=Capability.T2I,
        model_id=models[0].id,
        inputs={"prompt": "cube"},
    )
    provider.estimate(req)
    ref = provider.submit(req)
    status = provider.status(ref)
    assert status.state.value == "completed"
    assert cas.exists(status.outputs[0])
    assert "tools/call:generate_image" in calls
    assert "tools/call:get_generation" in calls


def test_oauth_endpoints_reject_private_targets() -> None:
    assert (
        _require_oauth_endpoint("http://127.0.0.1:9/token", allow_loopback=True)
        == "http://127.0.0.1:9/token"
    )
    with pytest.raises(OAuthError):
        _require_oauth_endpoint("http://127.0.0.1:9/token")
    with pytest.raises(OAuthError):
        _require_oauth_endpoint("http://169.254.169.254/latest")
    with pytest.raises(OAuthError):
        _require_oauth_endpoint("http://10.1.1.1/token")
    with pytest.raises(OAuthError):
        _require_oauth_endpoint("https://10.1.1.1/token")
    with pytest.raises(OAuthError):
        _require_oauth_endpoint("http://1.1.1.1/token")
    assert _require_oauth_endpoint("https://1.1.1.1/token") == "https://1.1.1.1/token"


def test_structured_tool_result_keeps_job_id() -> None:
    ref, status, b64 = parse_generate(
        {"content": [], "structuredContent": {"id": "job-9", "status": "running"}}
    )
    assert ref == "job-9"
    assert status.state.value == "running"
    assert b64 is None


def test_discovery_skips_private_urls() -> None:
    from vinci_mcp.oauth import _get_json

    assert _get_json("http://169.254.169.254/latest", allow_loopback=False) is None


def test_cancelled_provider_state_is_not_failed() -> None:
    status, _b64 = parse_status({"status": "cancelled"})
    assert status.state.value == "cancelled"


def test_public_host_oauth_requires_configured_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, oauth_server: OAuthServer
) -> None:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    monkeypatch.delenv("VINCI_PUBLIC_BASE_URL", raising=False)
    eng = Engine(tmp_path)
    eng.init_home(demo=True)
    client = TestClient(create_app(eng), base_url="http://evil.example")
    added = client.post(
        "/providers",
        json={"id": "mcp_magnific", "url": f"{oauth_server.origin}/mcp"},
    )
    assert added.status_code == 200, added.text
    started = client.post("/providers/mcp_magnific/oauth")
    assert started.status_code == 400
    assert "VINCI_PUBLIC_BASE_URL" in started.text
    monkeypatch.setenv("VINCI_PUBLIC_BASE_URL", "https://studio.example")
    started = client.post("/providers/mcp_magnific/oauth")
    assert started.status_code == 200, started.text
    assert "redirect_uri=https%3A%2F%2Fstudio.example%2Fproviders%2Foauth%2Fcallback" in (
        started.json()["authorize_url"]
    )
