from __future__ import annotations

import base64
import json
import uuid
from email.generator import BytesGenerator
from email.mime.multipart import MIMEMultipart
from email.policy import HTTP
from io import BytesIO
from typing import Any, Protocol

from vinci_protocol.enums import Capability, JobState
from vinci_protocol.models import (
    JobRequest,
    JobStatus,
    ModelSpec,
    ProviderAuth,
    ProviderJobRef,
    ProviderManifest,
)
from vinci_provider_sdk.catalog_provider import CatalogBackedProvider

OPENAI_IMAGES_URL = "https://api.openai.com/v1/images/generations"
OPENAI_EDITS_URL = "https://api.openai.com/v1/images/edits"

_ASPECT_TO_SIZE = {
    "1:1": "1024x1024",
    "16:9": "1536x1024",
    "9:16": "1024x1536",
}


class CasGet(Protocol):
    def get(self, digest: str) -> bytes: ...


class CasPut(Protocol):
    def put(self, data: bytes) -> str: ...


class CasStore(CasGet, CasPut, Protocol):
    pass


class OpenAIProvider(CatalogBackedProvider):
    durable_job_reconciliation = False
    catalog_name = "openai"
    provider_id = "openai"
    secret_name = "OPENAI_API_KEY"
    manifest = ProviderManifest(
        id="openai",
        display_name="OpenAI",
        auth=ProviderAuth(env_vars=["OPENAI_API_KEY"]),
        docs_url="https://platform.openai.com/docs/guides/image-generation",
    )

    def __init__(self, api_key: str | None = None, *, cas: CasStore | None = None) -> None:
        super().__init__(api_key=api_key)
        self._cas = cas

    def _submit_live(self, req: JobRequest, spec: ModelSpec) -> ProviderJobRef:
        if self._cas is None:
            raise RuntimeError("openai live submit needs CAS")
        model = self._catalog.endpoint_for(spec.id) or spec.id.split(":")[1]
        size = _size_from_inputs(req.inputs)
        quality = str(req.inputs.get("quality") or "medium")
        cap = req.capability
        if cap in {Capability.I2I, Capability.EDIT_MULTI}:
            blob = _input_image_bytes(req.inputs, self._cas)
            body, content_type = _multipart_edit(
                model=model,
                prompt=str(req.inputs.get("prompt", "")),
                size=size,
                quality=quality,
                image_bytes=blob,
                filename="input.png",
            )
            url = OPENAI_EDITS_URL
        else:
            payload = {
                "model": model,
                "prompt": str(req.inputs.get("prompt", "")),
                "size": size,
                "quality": quality,
                "n": 1,
            }
            body = json.dumps(payload).encode("utf-8")
            content_type = "application/json"
            url = OPENAI_IMAGES_URL

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": content_type,
        }
        parsed = self._open_json_body(url, headers, body)
        image_b64 = _first_b64(parsed)
        out = base64.b64decode(image_b64)
        if not out:
            raise RuntimeError("openai submit returned empty image")
        digest = self._cas.put(out)
        ref = str(uuid.uuid4())
        self._jobs[ref] = JobStatus(state=JobState.COMPLETED, outputs=[digest], progress=1.0)
        return ProviderJobRef(provider="openai", ref=ref)

    def _status_live(self, ref: ProviderJobRef) -> JobStatus | None:
        return self._jobs.get(ref.ref)

    def _open_json_body(self, url: str, headers: dict[str, str], body: bytes) -> dict[str, Any]:
        import urllib.error
        import urllib.request

        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise exc
        parsed: dict[str, Any] = json.loads(raw) if raw else {}
        return parsed


def _size_from_inputs(inputs: dict[str, Any]) -> str:
    explicit = inputs.get("size")
    if isinstance(explicit, str) and explicit:
        return explicit
    aspect = str(inputs.get("aspect_ratio") or "1:1")
    return _ASPECT_TO_SIZE.get(aspect, "1024x1024")


def _input_image_bytes(inputs: dict[str, Any], cas: CasGet) -> bytes:
    for key in ("media", "image", "still"):
        value = inputs.get(key)
        if isinstance(value, str) and value.strip():
            return cas.get(value.strip())
    raise ValueError("i2i/edit requires inputs.media or inputs.image (asset digest)")


def _first_b64(body: dict[str, Any]) -> str:
    data = body.get("data")
    if isinstance(data, list) and data:
        row = data[0]
        if isinstance(row, dict) and row.get("b64_json"):
            return str(row["b64_json"])
    raise RuntimeError("openai response missing data[].b64_json")


def _multipart_edit(
    *,
    model: str,
    prompt: str,
    size: str,
    quality: str,
    image_bytes: bytes,
    filename: str,
) -> tuple[bytes, str]:
    from email.mime.application import MIMEApplication
    from email.mime.nonmultipart import MIMENonMultipart

    root = MIMEMultipart("form-data", policy=HTTP)
    for field, value in (
        ("model", model),
        ("prompt", prompt),
        ("size", size),
        ("quality", quality),
        ("n", "1"),
    ):
        piece = MIMENonMultipart("form-data", field, policy=HTTP)
        piece.set_payload(value)
        piece["Content-Disposition"] = f'form-data; name="{field}"'
        root.attach(piece)
    file_part = MIMEApplication(image_bytes, _subtype="octet-stream")
    file_part["Content-Disposition"] = f'form-data; name="image[]"; filename="{filename}"'
    root.attach(file_part)
    buf = BytesIO()
    BytesGenerator(buf, policy=HTTP).flatten(root)  # type: ignore[arg-type]
    payload = buf.getvalue()
    content_type = root.get("Content-Type", "multipart/form-data")
    if not isinstance(content_type, str):
        content_type = str(content_type)
    return payload, content_type
