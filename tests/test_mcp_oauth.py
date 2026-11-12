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
from vinci_mcp.oauth import (
    OAuthError,
    _require_oauth_endpoint,
    access_token,
    clear_pending,
    result_page,
)
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
    # The resource's scopes, plus offline_access from the auth server (COREPRODUC-610).
    assert "scope=openid+email+mcp%3Acustom-audience+offline_access" in body["authorize_url"]
    landed = _redirect_target(body["authorize_url"])
    assert "code=" in landed and "state=" in landed
    query = landed.split("?", 1)[1]
    callback = client.get(f"/providers/oauth/callback?{query}")
    assert callback.status_code == 200
    assert "Signed in" in callback.text and "You can close this tab." in callback.text
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
        if name == "simulate_cost":  # the free price preview before the run
            return {"structuredContent": {"credits": 50, "certainty": "exact"}}
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
            "model_id": "mcp_magnific:seedream-4-5",
        },
    )
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["state"] == "completed"
    assert body["estimate"]["currency"] == "USD"
    assert body["estimate"]["total"] == 0
    assert body["estimate"]["nodes"][0]["currency"] == "Magnific credits"
    blob = base64.b64decode(PNG_B64)
    assert eng.cas.exists(body["outputs"][0])
    assert eng.cas.get(body["outputs"][0]) == blob
    job_id = body["job_ids"][0]
    job = eng.store.get_job(job_id)
    assert job is not None and job.receipt is not None
    receipt = job.receipt
    assert receipt.currency == "Magnific credits"
    assert receipt.computed_cost == 50.0
    assert eng.store.month_spend() == 0


def test_connector_submit_via_provider(tmp_path: Path) -> None:
    """Higgsfield, with the envelopes of its live tools (2026-11-12): results[0] and generation."""
    calls: list[tuple[str, dict[str, object]]] = []

    class Transport:
        url = "http://127.0.0.1:9/mcp"

        def bearer(self) -> str:
            return "loopback-bearer"

        def call(self, method: str, params: dict[str, object]) -> dict[str, object]:
            if method == "tools/list":
                return {"tools": [{"name": "generate_image"}, {"name": "generate_video"}, {"name": "job_status"}]}
            name, args = str(params.get("name")), params.get("arguments") or {}
            calls.append((name, args))  # type: ignore[arg-type]
            if name == "generate_image" and args["params"].get("get_cost"):  # type: ignore[index]
                return {"structuredContent": {"cost": {"credits": 1, "credits_exact": 1}}}
            if name == "generate_image":
                return {"structuredContent": {"results": [{"id": "h1", "status": "queued"}]}}
            return {"structuredContent": {"generation": {"id": "h1", "status": "completed", "results": {"rawUrl": "https://cdn.example/h1.png"}}}}

    cas = ContentAddressedStore(tmp_path / "cas")
    provider = McpProvider(Transport(), cas=cas, provider_id="mcp_higgsfield")  # type: ignore[arg-type]
    models = {m.id: m for m in provider.catalog()}
    row = models["mcp_higgsfield:seedream_v4_5"]
    assert row.pricing.currency == "Higgsfield credits" and row.pricing.amount == 1
    assert models["mcp_higgsfield:minimax_hailuo"].constraints.durations == [6.0]
    req = JobRequest(capability=Capability.T2I, model_id=row.id, inputs={"prompt": "cube", "aspect_ratio": "16:9"})
    provider.estimate(req)
    ref = provider.submit(req)
    status = provider.status(ref)
    assert status.state.value == "completed"
    assert status.outputs == ["https://cdn.example/h1.png"]
    preview, generate, poll = calls
    assert preview[1]["params"]["get_cost"] is True  # type: ignore[index]
    assert generate[1] == {"params": {"model": "seedream_v4_5", "prompt": "cube", "count": 1, "use_unlim": False, "aspect_ratio": "16:9"}}
    assert poll == ("job_status", {"jobId": "h1"})


def test_connector_uploads_the_start_frame(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Image to video: the start frame goes to the provider's storage first, then its id goes in the run."""
    puts: list[tuple[str, str]] = []
    monkeypatch.setattr("vinci_mcp.adapter._put", lambda url, data, kind: puts.append((url, kind)))
    cas = ContentAddressedStore(tmp_path / "cas")
    still = cas.put(base64.b64decode(PNG_B64))
    seen: dict[str, list[dict[str, object]]] = {}

    def transport(answers: dict[str, dict[str, object]]) -> object:
        class Transport:
            url = "http://127.0.0.1:9/mcp"

            def bearer(self) -> str:
                return "loopback-bearer"

            def call(self, method: str, params: dict[str, object]) -> dict[str, object]:
                if method == "tools/list":
                    return {"tools": [{"name": name} for name in answers]}
                name = str(params.get("name"))
                seen.setdefault(name, []).append(params.get("arguments") or {})  # type: ignore[arg-type]
                return {"structuredContent": answers[name]}

        return Transport()

    higgsfield = McpProvider(transport({  # type: ignore[arg-type]
        "media_upload": {"uploads": [{"upload_url": "https://up.example/1", "media_id": "m1", "content_type": "image/png"}]},
        "media_confirm": {"results": [{"media_id": "m1"}]},
        "generate_video": {"results": [{"id": "v1", "status": "queued"}]},
    }), cas=cas, provider_id="mcp_higgsfield")
    req = JobRequest(capability=Capability.I2V, model_id="mcp_higgsfield:minimax_hailuo", inputs={"prompt": "push in", "image": still})
    seen["generate_video"] = []
    higgsfield.estimate(req)
    higgsfield.submit(req)
    assert seen["media_confirm"] == [{"type": "image", "media_id": "m1"}]
    params = seen["generate_video"][-1]["params"]  # type: ignore[index]
    assert params["medias"] == [{"value": "m1", "role": "start_image"}]  # type: ignore[index]
    assert (params["variant"], params["duration"], params["resolution"]) == ("minimax-2.3-fast", 6, "768")  # type: ignore[index]

    seen.clear()
    magnific = McpProvider(transport({  # type: ignore[arg-type]
        "creations_request_upload": {"proxyUploadUrl": "https://up.example/2", "path": "tmp/2.png"},
        "creations_finalize_upload": {"identifier": "c9", "status": "ok"},
        "simulate_cost": {"credits": 150, "certainty": "exact"},
        "video_generate": {"creation": {"identifier": "v2", "status": "queued", "credits": 150}},
    }), cas=cas, provider_id="mcp_magnific")
    req = JobRequest(capability=Capability.I2V, model_id="mcp_magnific:minimax-video-2_3-fast", inputs={"prompt": "push in", "image": still, "aspect_ratio": "1:1"})
    magnific.estimate(req)
    ref = magnific.submit(req)
    assert ref.ref == "v2"
    assert seen["creations_finalize_upload"][0]["visible"] is False
    args = seen["video_generate"][0]
    # 1:1 is not a shape of this model: the model's own 16:9 goes out.
    assert args == {"prompt": "push in", "duration": 6, "resolution": "768p", "slug": "minimax-video-2_3-fast", "aspectRatio": "16:9", "keyframes": {"start": "c9"}}
    assert [url for url, _kind in puts] == ["https://up.example/1", "https://up.example/2"]


def test_connector_stops_when_the_live_price_is_higher(tmp_path: Path) -> None:
    """The free preview says more than the row: nothing runs."""
    generated: list[str] = []

    class Transport:
        url = "http://127.0.0.1:9/mcp"

        def bearer(self) -> str:
            return "loopback-bearer"

        def call(self, method: str, params: dict[str, object]) -> dict[str, object]:
            if method == "tools/list":
                return {"tools": [{"name": "images_generate"}]}
            if params.get("name") == "simulate_cost":
                return {"structuredContent": {"credits": 80}}
            generated.append(str(params.get("name")))
            return {"structuredContent": {"creation": {"identifier": "c1"}}}

    provider = McpProvider(Transport(), cas=ContentAddressedStore(tmp_path / "cas"), provider_id="mcp_magnific")  # type: ignore[arg-type]
    req = JobRequest(capability=Capability.T2I, model_id="mcp_magnific:mystic-2-5", inputs={"prompt": "cube"})
    provider.estimate(req)
    with pytest.raises(ValueError, match="costs 80 Magnific credits now, not 50"):
        provider.submit(req)
    assert generated == []


def test_provider_envelopes_and_refusals() -> None:
    done, _ = parse_status({"structuredContent": {"creationIdentifier": "c1", "status": "COMPLETED", "results": {"url": "https://cdn.example/c1.png"}}})
    assert done.state.value == "completed" and done.outputs == ["https://cdn.example/c1.png"]
    held, _ = parse_status({"structuredContent": {"generation": {"id": "h1", "status": "ip_detect"}}})
    assert held.state.value == "failed" and "IP check" in (held.error.message if held.error else "")
    failed, _ = parse_status({"structuredContent": {"status": "FAILED", "failureReason": "prompt blocked"}})
    assert failed.error is not None and failed.error.message == "prompt blocked"
    with pytest.raises(RuntimeError, match="Not enough credits"):
        parse_generate({"structuredContent": {"error": "Not enough credits", "results": []}})


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


def test_scope_falls_back_without_resource_scopes() -> None:
    """No resource scopes: the old openid + offline_access pair from the auth server."""
    from vinci_mcp.oauth import _scope

    assert _scope({"scopes_supported": ["openid", "offline_access", "profile"]}) == "openid offline_access"
    assert _scope({"scopes_supported": ["profile"]}) == ""
    assert _scope({}) == ""
    # Higgsfield lists offline_access itself: it is not asked twice.
    higgsfield = {"resource_scopes": ["openid", "email", "offline_access"], "scopes_supported": ["offline_access"]}
    assert _scope(higgsfield) == "openid email offline_access"


def test_pending_sign_in_moves_between_processes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, oauth_server: OAuthServer
) -> None:
    """A host keeps the pending sign-in and gives it back where the callback lands (COREPRODUC-614)."""
    from vinci_core.config import load_config
    from vinci_core.credentials import CredentialResolver
    from vinci_mcp.oauth import finish, pending_export, pending_import, start

    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    Engine(tmp_path).init_home(demo=True)
    resolver = CredentialResolver(load_config(tmp_path))
    started = start(resolver, "mcp_magnific", f"{oauth_server.origin}/mcp", "http://127.0.0.1:9/cb")
    landed = _redirect_target(started["authorize_url"])
    query = dict(item.split("=", 1) for item in landed.split("?", 1)[1].split("&"))
    kept = pending_export(query["state"])
    assert kept and kept["provider_id"] == "mcp_magnific"
    clear_pending()  # another process: nothing pending here
    pending_import(query["state"], kept)
    assert finish(resolver, code=query["code"], state=query["state"])["auth_state"] == "connected"
    assert access_token(resolver, "mcp_magnific")


def test_result_page_names_the_provider_and_escapes() -> None:
    """One sign-in result page for the daemon and the hosted backend (COREPRODUC-614)."""
    done = result_page("Higgsfield")
    assert "Signed in to Higgsfield" in done and "Your Higgsfield models" in done
    assert 'class="ok"' in done and "<script" not in done
    assert "<h1>Signed in</h1>" in result_page("")  # another server: no preset name
    failed = result_page("", "unknown <b>state</b>")
    assert "Sign-in did not finish" in failed and 'class="bad"' in failed
    assert "Unknown &lt;b&gt;state&lt;/b&gt;" in failed and "<b>" not in failed
