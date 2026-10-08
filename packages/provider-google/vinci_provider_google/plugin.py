from __future__ import annotations

import os
import uuid
from typing import Any

from vinci_protocol.enums import ErrorCode, JobState
from vinci_protocol.models import (
    JobRequest,
    JobStatus,
    ModelSpec,
    ProviderAuth,
    ProviderJobRef,
    ProviderManifest,
    VinciError,
)
from vinci_provider_sdk.catalog_provider import CatalogBackedProvider


def _inline_data_uris(body: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for candidate in body.get("candidates") or []:
        if not isinstance(candidate, dict):
            continue
        parts = ((candidate.get("content") or {}).get("parts") or [])
        for part in parts:
            if not isinstance(part, dict):
                continue
            inline = part.get("inlineData") or part.get("inline_data") or {}
            if not isinstance(inline, dict):
                continue
            data = inline.get("data")
            mime = str(inline.get("mimeType") or inline.get("mime_type") or "image/png")
            if data:
                out.append(f"data:{mime};base64,{data}")
    return out


def _http_urls(payload: Any) -> list[str]:
    found: list[str] = []

    def walk(obj: Any) -> None:
        if isinstance(obj, str) and obj.startswith(("http://", "https://")):
            found.append(obj)
        elif isinstance(obj, dict):
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for value in obj:
                walk(value)

    walk(payload)
    out: list[str] = []
    seen: set[str] = set()
    for url in found:
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


class GoogleProvider(CatalogBackedProvider):
    durable_job_reconciliation = True
    catalog_name = "google"
    provider_id = "google"
    secret_name = "GEMINI_API_KEY"
    manifest = ProviderManifest(
        id="google",
        display_name="Google",
        auth=ProviderAuth(env_vars=["GEMINI_API_KEY"]),
        docs_url="https://aistudio.google.com/apikey",
    )

    def _headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json", "x-goog-api-key": str(self._api_key)}

    def _root(self) -> str:
        return os.environ.get(
            "GEMINI_API_URL", "https://generativelanguage.googleapis.com"
        ).rstrip("/")

    def _submit_live(self, req: JobRequest, spec: ModelSpec) -> ProviderJobRef:
        model = self._catalog.endpoint_for(spec.id) or spec.id.split(":")[1]
        caps = {cap.value for cap in spec.capabilities}
        if "t2v" in caps or "i2v" in caps:
            return self._submit_veo(req, model)
        url = f"{self._root()}/v1beta/models/{model}:generateContent"
        payload: dict[str, Any] = {
            "contents": [{"parts": [{"text": self.prompt_text(req)}]}],
        }
        body = self._post_json(url, self._headers(), payload)
        outputs = _inline_data_uris(body)
        if not outputs:
            raise RuntimeError("google generateContent missing image")
        ref = str(body.get("responseId") or body.get("name") or uuid.uuid4())
        self._jobs[ref] = JobStatus(state=JobState.COMPLETED, outputs=outputs, progress=1.0)
        return ProviderJobRef(provider="google", ref=ref)

    def _submit_veo(self, req: JobRequest, model: str) -> ProviderJobRef:
        url = f"{self._root()}/v1beta/models/{model}:predictLongRunning"
        instance: dict[str, Any] = {"prompt": self.prompt_text(req)}
        image = req.inputs.get("image") or req.inputs.get("image_url")
        if isinstance(image, str) and image.startswith(("http://", "https://")):
            instance["image"] = {"uri": image}
        parameters: dict[str, Any] = {
            "aspectRatio": str(req.inputs.get("aspect_ratio") or "16:9"),
        }
        duration = req.inputs.get("duration")
        if duration not in (None, ""):
            try:
                parameters["durationSeconds"] = int(duration)
            except (TypeError, ValueError):
                pass
        payload: dict[str, Any] = {
            "instances": [instance],
            "parameters": parameters,
        }
        body = self._post_json(url, self._headers(), payload)
        name = str(body.get("name") or "")
        if "operations" not in name:
            raise RuntimeError("google veo submit missing operation name")
        return ProviderJobRef(provider="google", ref=name)

    def _status_live(self, ref: ProviderJobRef) -> JobStatus | None:
        name = ref.ref.strip().lstrip("/")
        if "operations" not in name:
            return None
        url = f"{self._root()}/v1beta/{name}"
        body = self._get_json(url, self._headers())
        error = body.get("error")
        if isinstance(error, dict):
            return JobStatus(
                state=JobState.FAILED,
                error=VinciError(
                    code=ErrorCode.UNKNOWN,
                    message=str(error.get("message") or "failed"),
                    retryable=True,
                ),
            )
        if not body.get("done"):
            return JobStatus(state=JobState.RUNNING, outputs=[], progress=0.5)
        outputs = _http_urls(body.get("response") or body)
        return JobStatus(state=JobState.COMPLETED, outputs=outputs, progress=1.0)
