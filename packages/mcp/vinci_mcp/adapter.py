"""Adapter: treat an external MCP server as a Vinci Provider.

Estimate from the remote catalog (or a supplied snapshot). Submit is allowed
on loopback transports at $0 for image and video generate, or when
VINCI_ALLOW_LIVE_SPEND=1. Keys never go in logs or MCP payloads.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import urlparse

from vinci_core.cost import estimate_from_spec, idempotency_key
from vinci_core.paths import allow_live_spend
from vinci_core.redact import redact_mapping
from vinci_protocol.enums import Capability, ErrorCode, JobState
from vinci_protocol.models import (
    Estimate,
    JobRequest,
    JobStatus,
    ModelSpec,
    Pricing,
    ProviderAuth,
    ProviderJobRef,
    ProviderManifest,
    VinciError,
)
from vinci_provider_sdk.base import Provider
from vinci_provider_sdk.catalog_provider import LiveSpendDisabled

from vinci_mcp.connectors import (
    connector_for,
    decode_b64,
    models_for,
    parse_generate,
    parse_status,
)

log = logging.getLogger("vinci.mcp.adapter")

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
_IMAGE_CAPS = {Capability.T2I, Capability.I2I, Capability.EDIT_MULTI}
_VIDEO_CAPS = {Capability.T2V, Capability.I2V}
_SUBMIT_CAPS = _IMAGE_CAPS | _VIDEO_CAPS


class McpTransport(Protocol):
    def call(self, method: str, params: dict[str, Any]) -> Any: ...


class CasPut(Protocol):
    def put(self, data: bytes) -> str: ...


class HttpMcpTransport:
    """Streamable-HTTP MCP session. Sends the bearer the adapter used to drop."""

    def __init__(
        self,
        url: str,
        timeout: float = 30.0,
        *,
        token_provider: Callable[[], str | None] | None = None,
    ) -> None:
        self.url = url
        self.timeout = timeout
        self._token_provider = token_provider

    def bearer(self) -> str | None:
        if self._token_provider is None:
            return None
        token = self._token_provider()
        return token if isinstance(token, str) and token else None

    def call(self, method: str, params: dict[str, Any]) -> Any:
        # Loopback fixtures and the local Vinci MCP server speak one-shot JSON-RPC.
        # Remote connectors use the SDK streamable-HTTP session.
        host = (urlparse(self.url).hostname or "").lower()
        if host in _LOOPBACK_HOSTS:
            return self._jsonrpc(method, params)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return self._run_sdk(method, params)
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            return pool.submit(self._run_sdk, method, params).result()
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def _run_sdk(self, method: str, params: dict[str, Any]) -> Any:
        return asyncio.run(asyncio.wait_for(self._sdk_call(method, params), self.timeout))

    def _jsonrpc(self, method: str, params: dict[str, Any]) -> Any:
        headers = {"content-type": "application/json"}
        token = self.bearer()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        opener = urllib.request.build_opener(_RefuseRedirect)
        with opener.open(request, timeout=self.timeout) as response:
            raw = response.read().decode("utf-8")
        body = json.loads(raw) if raw else {}
        if not isinstance(body, dict):
            raise RuntimeError("mcp transport returned a non-object")
        if body.get("error"):
            raise RuntimeError(str(body["error"]))
        return body.get("result")

    async def _sdk_call(self, method: str, params: dict[str, Any]) -> Any:
        import httpx
        from mcp.client.streamable_http import streamable_http_client

        from mcp import ClientSession

        headers: dict[str, str] = {}
        token = self.bearer()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        timeout = httpx.Timeout(self.timeout)
        async with httpx.AsyncClient(
            headers=headers, timeout=timeout, follow_redirects=False
        ) as http:
            async with streamable_http_client(self.url, http_client=http) as streams:
                read, write = streams[0], streams[1]
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    if method == "tools/list":
                        listed = await session.list_tools()
                        return {
                            "tools": [
                                {"name": tool.name, "description": tool.description or ""}
                                for tool in listed.tools
                            ]
                        }
                    if method == "tools/call":
                        name = str(params.get("name") or "")
                        arguments = params.get("arguments")
                        payload = arguments if isinstance(arguments, dict) else {}
                        result = await session.call_tool(name, payload)
                        content: list[dict[str, str]] = []
                        for block in result.content:
                            text = getattr(block, "text", None)
                            if isinstance(text, str):
                                content.append({"type": "text", "text": text})
                                continue
                            data = getattr(block, "data", None)
                            if isinstance(data, str) and data:
                                mime = getattr(block, "mimeType", None) or "image/png"
                                content.append(
                                    {"type": "image", "data": data, "mimeType": str(mime)}
                                )
                        body: dict[str, Any] = {
                            "content": content,
                            "isError": bool(result.isError),
                        }
                        structured = getattr(result, "structuredContent", None)
                        if isinstance(structured, dict):
                            body["structuredContent"] = structured
                        return body
                    raise RuntimeError(f"unsupported mcp method {method}")


class McpProvider(Provider):
    manifest = ProviderManifest(
        id="mcp",
        display_name="External MCP",
        auth=ProviderAuth(env_vars=["MCP_API_KEY"]),
    )

    def __init__(
        self,
        transport: McpTransport,
        *,
        models: list[ModelSpec] | None = None,
        api_key: str | None = None,
        catalog_tool: str = "vinci.models_list",
        generate_tool: str = "vinci.image_generate",
        video_tool: str = "vinci.video_generate",
        cas: CasPut | None = None,
        provider_id: str = "mcp",
    ) -> None:
        self._transport = transport
        self._models = list(models or [])
        self._api_key = api_key
        self._catalog_tool = catalog_tool
        self._generate_tool = generate_tool
        self._video_tool = video_tool
        self._cas = cas
        self._provider_id = provider_id
        self._connector = connector_for(provider_id)
        self._estimated: set[str] = set()
        self._jobs: dict[str, JobStatus] = {}

    def _secret(self) -> str | None:
        bearer = getattr(self._transport, "bearer", None)
        if callable(bearer):
            token = bearer()
            if isinstance(token, str) and token:
                return token
        return self._api_key

    def catalog(self) -> list[ModelSpec]:
        if self._connector is not None:
            names: set[str] | None
            try:
                listed = self._transport.call("tools/list", {})
                rows = listed.get("tools") if isinstance(listed, dict) else None
                names = {
                    str(row.get("name"))
                    for row in rows or []
                    if isinstance(row, dict) and row.get("name")
                }
            except Exception as exc:  # noqa: BLE001 — catalog falls back to the mapping
                log.warning("mcp tools/list failed type=%s", type(exc).__name__)
                names = None
            return models_for(self._connector, names)
        if self._models:
            return list(self._models)
        result = self._transport.call(
            "tools/call", {"name": self._catalog_tool, "arguments": {}}
        )
        rows = _models_from_result(result)
        self._models = rows
        return list(rows)

    def capabilities(self) -> set[Capability]:
        caps: set[Capability] = set()
        for model in self.catalog():
            caps.update(model.capabilities)
        return caps

    def estimate(self, req: JobRequest) -> Estimate:
        models = self.catalog()
        if not models:
            raise KeyError("mcp catalog is empty")
        spec = _pick_model(models, req)
        key = req.idempotency_key or idempotency_key(spec.id, req.inputs)
        self._estimated.add(key)
        secret = self._secret()
        extra = [secret] if secret else []
        log.info(
            "estimate provider=mcp model=%s inputs=%s",
            spec.id,
            redact_mapping(req.inputs, extra_values=extra),
        )
        return estimate_from_spec(spec)

    def submit(self, req: JobRequest) -> ProviderJobRef:
        models = self.catalog()
        spec = _pick_model(models, req)
        key = req.idempotency_key or idempotency_key(spec.id, req.inputs)
        if key not in self._estimated:
            raise RuntimeError("estimate() must be called before submit()")
        secret = self._secret()
        extra = [secret] if secret else []
        log.info(
            "submit provider=mcp model=%s inputs=%s",
            spec.id,
            redact_mapping(req.inputs, extra_values=extra),
        )
        if not secret:
            raise PermissionError("missing MCP_API_KEY")
        if not _is_loopback_transport(self._transport) and not allow_live_spend():
            raise LiveSpendDisabled(
                "live provider spend is disabled; set VINCI_ALLOW_LIVE_SPEND=1 to enable"
            )
        if req.capability not in _SUBMIT_CAPS:
            raise ValueError("mcp adapter submit supports image and video generation only")
        if self._cas is None:
            raise RuntimeError("mcp submit requires a content-addressed store")
        if self._connector is not None:
            return self._submit_connector(req, spec)
        result = self._transport.call(
            "tools/call",
            {
                "name": self._tool_for(req.capability),
                "arguments": {
                    "prompt": req.inputs.get("prompt"),
                    "model_id": spec.id,
                },
            },
        )
        blob = _bytes_from_result(result)
        digest = self._cas.put(blob)
        ref = str(uuid.uuid4())
        self._jobs[ref] = JobStatus(
            state=JobState.COMPLETED, outputs=[digest], progress=1.0
        )
        return ProviderJobRef(provider=self._provider_id, ref=ref)

    def _submit_connector(self, req: JobRequest, spec: ModelSpec) -> ProviderJobRef:
        if self._connector is None or self._cas is None:
            raise RuntimeError("mcp connector is not configured")
        result = self._transport.call(
            "tools/call",
            {
                "name": self._connector.tool_for(req.capability),
                "arguments": self._connector.arguments(req.capability, req.inputs),
            },
        )
        ref, status, b64 = parse_generate(result)
        status = self._attach_bytes(status, b64)
        self._jobs[ref] = status
        del spec
        return ProviderJobRef(provider=self._provider_id, ref=ref)

    def _attach_bytes(self, status: JobStatus, b64: str | None) -> JobStatus:
        if not b64 or self._cas is None:
            return status
        digest = self._cas.put(decode_b64(b64))
        outputs = [digest, *status.outputs]
        return status.model_copy(
            update={"outputs": outputs, "state": JobState.COMPLETED, "progress": 1.0}
        )

    def status(self, ref: ProviderJobRef) -> JobStatus:
        cached = self._jobs.get(ref.ref)
        if cached is not None and cached.state in {
            JobState.COMPLETED,
            JobState.FAILED,
            JobState.CANCELLED,
        }:
            return cached
        if self._connector is not None and self._connector.status_tool:
            result = self._transport.call(
                "tools/call",
                {"name": self._connector.status_tool, "arguments": {"id": ref.ref}},
            )
            status, b64 = parse_status(result)
            status = self._attach_bytes(status, b64)
            self._jobs[ref.ref] = status
            return status
        if cached is not None:
            return cached
        return JobStatus(
            state=JobState.FAILED,
            error=VinciError(code=ErrorCode.UNKNOWN, message="unknown mcp job"),
        )

    def _tool_for(self, capability: Capability) -> str:
        if capability in _VIDEO_CAPS:
            return self._video_tool
        return self._generate_tool

    def cancel(self, ref: ProviderJobRef) -> None:
        current = self._jobs.get(ref.ref)
        if current is not None:
            self._jobs[ref.ref] = JobStatus(state=JobState.CANCELLED)

    def normalize_error(self, exc: BaseException) -> VinciError:
        if isinstance(exc, PermissionError):
            return VinciError(code=ErrorCode.AUTH, message="auth failed", retryable=False)
        if isinstance(exc, LiveSpendDisabled):
            return VinciError(code=ErrorCode.UNKNOWN, message=str(exc), retryable=False)
        if isinstance(exc, KeyError | ValueError):
            return VinciError(code=ErrorCode.INVALID_INPUT, message=str(exc), retryable=False)
        if isinstance(exc, urllib.error.HTTPError) and exc.code in {401, 403}:
            return VinciError(code=ErrorCode.AUTH, message="provider auth failed", retryable=False)
        return VinciError(code=ErrorCode.UNKNOWN, message=type(exc).__name__, retryable=False)


def _pick_model(models: list[ModelSpec], req: JobRequest) -> ModelSpec:
    if req.model_id:
        for model in models:
            if model.id == req.model_id:
                return model
        raise KeyError(req.model_id)
    cap = req.capability.value
    hits = [m for m in models if cap in [c.value for c in m.capabilities]]
    if not hits:
        raise KeyError(f"no model for {cap}")
    return min(hits, key=lambda m: m.pricing.amount)


def _payload_from_result(result: Any) -> Any:
    payload = result
    if isinstance(result, dict) and "content" in result:
        texts = [
            block.get("text")
            for block in result.get("content") or []
            if isinstance(block, dict)
        ]
        for text in texts:
            if not isinstance(text, str):
                continue
            try:
                payload = json.loads(text)
                break
            except json.JSONDecodeError:
                continue
    return payload


def _models_from_result(result: Any) -> list[ModelSpec]:
    payload = _payload_from_result(result)
    if isinstance(payload, dict):
        rows = payload.get("models") or payload.get("catalog") or []
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = []
    models: list[ModelSpec] = []
    now = datetime.now(tz=UTC)
    for row in rows:
        if isinstance(row, ModelSpec):
            models.append(row)
            continue
        if not isinstance(row, dict):
            continue
        if "pricing" not in row:
            row = {
                **row,
                "pricing": Pricing(
                    unit="call", amount=0.0, currency="USD", snapshot_at=now
                ).model_dump(mode="json"),
            }
        models.append(ModelSpec.model_validate(row))
    return models


def _bytes_from_result(result: Any) -> bytes:
    if isinstance(result, dict):
        for block in result.get("content") or []:
            if (
                isinstance(block, dict)
                and block.get("type") == "image"
                and isinstance(block.get("data"), str)
            ):
                try:
                    return base64.b64decode(block["data"], validate=True)
                except Exception as exc:  # noqa: BLE001 — invalid image data is invalid input
                    raise ValueError("mcp generate returned invalid b64") from exc
    payload = _payload_from_result(result)
    if not isinstance(payload, dict):
        raise ValueError("mcp generate returned no media bytes")
    raw = payload.get("b64") or payload.get("base64")
    if not isinstance(raw, str) or not raw:
        raise ValueError("mcp generate returned no media bytes")
    try:
        return base64.b64decode(raw, validate=True)
    except Exception as exc:  # noqa: BLE001 — invalid b64 is invalid input
        raise ValueError("mcp generate returned invalid b64") from exc


class _RefuseRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(  # noqa: PLR6301 — urllib calls this unbound-style
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        del self, req, fp, code, msg, headers, newurl
        raise RuntimeError("mcp redirect refused")


def _transport_url(transport: McpTransport) -> str | None:
    url = getattr(transport, "url", None)
    return url if isinstance(url, str) and url else None


def _is_loopback_transport(transport: McpTransport) -> bool:
    url = _transport_url(transport)
    if not url:
        return False
    host = (urlparse(url).hostname or "").lower()
    return host in _LOOPBACK_HOSTS
