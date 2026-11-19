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
import re
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
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
from vinci_provider_sdk.local_image import sniff_media_mime

from vinci_mcp.connectors import (
    SNAPSHOT,
    connector_for,
    decode_b64,
    models_for,
    parse_balance,
    parse_cost,
    parse_generate,
    parse_status,
    payload_from_tool,
)

log = logging.getLogger("vinci.mcp.adapter")


class SessionEnded(RuntimeError):
    """The provider ended the account session behind a valid token: sign in again.

    Bug fixed 2026-11-18 (COREPRODUC-677, recurring: 2 episodes on one account, 48 h and 67 h
    after a sign-in): Higgsfield answered "FNF API GET /mcp/workspaces failed (403)" while its
    tokens still refreshed, so Connect said "connected" and every run failed.
    """

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
_IMAGE_CAPS = {Capability.T2I, Capability.I2I, Capability.EDIT_MULTI}
_VIDEO_CAPS = {Capability.T2V, Capability.I2V, Capability.R2V}  # r2v: a pin video render (#732)
_SUBMIT_CAPS = _IMAGE_CAPS | _VIDEO_CAPS


class McpTransport(Protocol):
    def call(self, method: str, params: dict[str, Any]) -> Any: ...


class CasPut(Protocol):
    """The content store: ``put`` keeps outputs; ``get`` and ``exists`` read a start frame."""

    def put(self, data: bytes) -> str: ...

    def get(self, digest: str) -> bytes: ...

    def exists(self, digest: str) -> bool: ...


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

        from mcp import ClientSession

        headers: dict[str, str] = {}
        token = self.bearer()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        timeout = httpx.Timeout(self.timeout)
        async with httpx.AsyncClient(
            headers=headers, timeout=timeout, follow_redirects=False
        ) as http:
            async with _streams(self.url, http, headers, self.timeout) as streams:
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
        on_session_ended: Callable[[], None] | None = None,
    ) -> None:
        self._transport = transport
        self._models = list(models or [])
        self._api_key = api_key
        self._catalog_tool = catalog_tool
        self._generate_tool = generate_tool
        self._video_tool = video_tool
        self._cas = cas
        self._provider_id = provider_id
        self._on_session_ended = on_session_ended  # marks the sign-in "needs_reconnect"
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
        """Run one connector row: upload the start frame, check the live price, then generate.

        The provider's free price preview runs first. A run whose live price is above its row's
        price stops before any spend (the Studio showed the row's price).
        """
        connector = self._connector
        if connector is None or self._cas is None:
            raise RuntimeError("mcp connector is not configured")
        row = connector.row(spec.id)
        tool = connector.tools[row.capability]
        inputs = req.inputs
        start = end = None
        videos: tuple[str, ...] = ()
        if row.reference:  # the pin video and the pictures; no start frame (COREPRODUC-732)
            clips = [v for v in inputs.get("reference_videos") or [] if isinstance(v, str) and v]
            if not clips:
                raise ValueError("a reference render needs its pin video (reference_videos)")
            videos = tuple(self._upload(clip, "video") for clip in clips[: row.video_refs])
            asked = inputs.get("reference_images")
        elif row.video:
            first = _image_ref(inputs)
            if first and "i2v" in row.capabilities:
                start = self._upload(first)
            elif "t2v" not in row.capabilities:
                raise ValueError("this model needs a start frame")
            last = inputs.get("last_frame_url") or inputs.get("tail_image_url")
            if start and row.end_frame and isinstance(last, str) and last:
                end = self._upload(last)
            asked = inputs.get("reference_urls")  # the Video page's References mode
        else:
            asked = inputs.get("image_urls") or ([inputs["image"]] if inputs.get("image") else [])
        # Reference images go to the provider's storage too (COREPRODUC-669): an image edit, or
        # a video's References mode.
        listed = [ref for ref in asked or [] if isinstance(ref, str) and ref][: row.refs]
        refs = tuple(self._upload(ref) for ref in listed)
        args = connector.arguments(row, inputs, start, end, refs, videos)
        preview_tool, preview = connector.cost_call(tool, args)
        live = parse_cost(self._call(preview_tool, preview))
        expected = row.price(row.length(inputs.get("duration")))
        log.info(
            "mcp price provider=%s model=%s live=%s row=%s refs=%s videos=%s end=%s",
            connector.id,
            row.key,
            live,
            expected,
            len(refs),
            len(videos),
            bool(end),
        )
        if live is not None and expected is not None and live > expected + 1e-9:
            raise ValueError(
                f"{spec.display_name} costs {live:g} {connector.currency} now, "
                f"not {expected:g}. Nothing ran."
            )
        ref, status, b64 = parse_generate(self._call(tool, args))
        log.info(
            "mcp submitted provider=%s model=%s ref=%s state=%s",
            connector.id,
            row.model,
            ref,
            status.state.value,
        )
        status = self._attach_bytes(status, b64)
        self._jobs[ref] = status
        return ProviderJobRef(provider=self._provider_id, ref=ref)

    def balance(self) -> float | None:
        """The credits on the signed-in account now, from the provider's free balance tool.

        Returns:
            The credits, or None when the connector has no balance tool or the answer has no number.

        Raises:
            RuntimeError: The provider refused the call (its message, for example a 403).
        """
        tool = self._connector.balance_tool if self._connector is not None else ""
        if not tool:
            return None
        credits = parse_balance(self._call(tool, {}))
        log.info("mcp balance provider=%s credits=%s", self._provider_id, credits)
        return credits

    def _call(self, name: str, arguments: dict[str, Any]) -> Any:
        """One tools/call. A tool error raises with the provider's message (no secrets in it).

        Raises:
            SessionEnded: The error says the provider ended the account session. The
                ``on_session_ended`` callback runs first. The call is not retried (it can be paid).
            RuntimeError: Any other tool error.
        """
        result = self._transport.call("tools/call", {"name": name, "arguments": arguments})
        if isinstance(result, dict) and result.get("isError"):
            texts = [b.get("text") for b in result.get("content") or [] if isinstance(b, dict)]
            message = next((t for t in texts if isinstance(t, str) and t), f"{name} failed")
            ended = self._connector.session_ended if self._connector is not None else ""
            if ended and re.search(ended, message):
                log.warning("mcp session ended provider=%s tool=%s", self._provider_id, name)
                if self._on_session_ended is not None:
                    self._on_session_ended()
                label = self._connector.label if self._connector is not None else self._provider_id
                raise SessionEnded(
                    f"{label} ended this sign-in on their side. "
                    f"Open Connect and sign in to {label} again."
                )
            raise RuntimeError(f"{self._provider_id} {name}: {message[:300]}")
        return result

    def _upload(self, ref: str, kind: str = "image") -> str:
        """Put one image (a start or end frame, a reference) or a video (a reference render's pin
        video) in the provider's storage; its id.

        A public https link is imported by the provider (Magnific reads a video's link as it is).
        A content digest or a ``data:`` URI is uploaded: Higgsfield ``media_upload`` + PUT +
        ``media_confirm``; Magnific ``creations_request_upload`` + PUT +
        ``creations_finalize_upload`` (not in the library).
        """
        higgsfield = self._provider_id == "mcp_higgsfield"
        if ref.startswith("https://"):
            if higgsfield:
                imported = self._call("media_import_url", {"url": ref, "type": kind})
                return _need(imported, "media_id")
            if kind == "video":  # an asset URL is a video reference as it is (video_generate)
                return ref
            uploaded = self._call(
                "creations_upload_image", {"url": ref, "fileName": "vinci-start.png"}
            )
            return _need(uploaded, "identifier")
        blob = self._image_bytes(ref)
        mime = sniff_media_mime(blob) or ("video/mp4" if kind == "video" else "image/png")
        stem = "vinci-pin." if kind == "video" else "vinci-start."
        name = stem + mime.split("/")[-1].replace("jpeg", "jpg")
        if higgsfield:
            asked = self._call("media_upload", {"filename": name, "content_type": mime})
            uploads = payload_from_tool(asked)
            upload = (uploads.get("uploads") or [{}])[0] if isinstance(uploads, dict) else {}
            media_id = _need(upload, "media_id")
            _put(_need(upload, "upload_url"), blob, str(upload.get("content_type") or mime))
            self._call("media_confirm", {"type": kind, "media_id": media_id})
            return media_id
        ticket = payload_from_tool(self._call("creations_request_upload", {"mimeType": mime}))
        _put(_need(ticket, "proxyUploadUrl"), blob, mime)
        done = self._call(
            "creations_finalize_upload",
            {"path": _need(ticket, "path"), "fileName": name, "visible": False},
        )
        return _need(done, "identifier")

    def _image_bytes(self, ref: str) -> bytes:
        if ref.startswith("data:"):
            return base64.b64decode(ref.split(",", 1)[-1], validate=False)
        cas = self._cas
        if cas is not None and cas.exists(ref):
            return cas.get(ref)
        raise ValueError("the start frame is not in this studio's store")

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
            connector = self._connector
            polled = self._call(connector.status_tool, {connector.status_arg: ref.ref})
            status, b64 = parse_status(polled)
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
        if isinstance(exc, SessionEnded):
            return VinciError(code=ErrorCode.AUTH, message=str(exc), retryable=False)
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
    for row in rows:
        if isinstance(row, ModelSpec):
            models.append(row)
            continue
        if not isinstance(row, dict):
            continue
        if "pricing" not in row:
            row = {
                **row,
                "pricing": Pricing(  # a fixed snapshot, so its cached results stay reusable
                    unit="call", amount=0.0, currency="USD", snapshot_at=SNAPSHOT
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


def _streams(url: str, http: Any, headers: dict[str, str], timeout: float) -> Any:
    """The SDK's streamable-HTTP client on any mcp 1.x, with redirects off.

    ``streamable_http_client`` (mcp 1.26+) takes our client. The older ``streamablehttp_client``
    gets a factory for the same client: the hosted backend pins mcp 1.12 through fastapi-mcp
    (COREPRODUC-614).
    """
    from mcp.client import streamable_http as sdk

    if hasattr(sdk, "streamable_http_client"):
        return sdk.streamable_http_client(url, http_client=http)
    import httpx

    def factory(headers: Any = None, timeout: Any = None, auth: Any = None) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers=headers, timeout=timeout, auth=auth, follow_redirects=False
        )

    return sdk.streamablehttp_client(
        url, headers=headers, timeout=timeout, httpx_client_factory=factory
    )


# Start-frame keys first: only video runs send them, and they win over `image` (COREPRODUC-644).
_START_KEYS = ("first_frame_url", "start_image_url", "image", "image_url", "media")


def _image_ref(inputs: dict[str, Any]) -> str | None:
    """The start frame of a run: the first image input (a digest, a ``data:`` URI or a link)."""
    for key in _START_KEYS:
        value = inputs.get(key)
        if isinstance(value, str) and value:
            return value
    listed = inputs.get("image_urls")
    if isinstance(listed, list) and listed and isinstance(listed[0], str):
        return listed[0]
    return None


def _need(payload: Any, key: str) -> str:
    """A required string field of a tool result or a plain object."""
    data = payload_from_tool(payload)
    value = data.get(key) if isinstance(data, dict) else None
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"mcp upload returned no {key}")
    return value


def _put(url: str, data: bytes, content_type: str) -> None:
    """PUT bytes to a provider's presigned upload link: https only, no redirects."""
    if not url.startswith("https://"):
        raise RuntimeError("the upload link is not https")
    # A named client: Higgsfield's upload host (Cloudflare) refuses Python's default User-Agent
    # with error 1010 (first seen in the live check, 2026-11-12).
    headers = {"Content-Type": content_type, "User-Agent": "vinci-studio/1.0"}
    request = urllib.request.Request(url, data=data, method="PUT", headers=headers)
    with urllib.request.build_opener(_RefuseRedirect).open(request, timeout=120) as response:
        if response.status >= 300:
            raise RuntimeError(f"upload failed: HTTP {response.status}")


def _transport_url(transport: McpTransport) -> str | None:
    url = getattr(transport, "url", None)
    return url if isinstance(url, str) and url else None


def _is_loopback_transport(transport: McpTransport) -> bool:
    url = _transport_url(transport)
    if not url:
        return False
    host = (urlparse(url).hostname or "").lower()
    return host in _LOOPBACK_HOSTS
