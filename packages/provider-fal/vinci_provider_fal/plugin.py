from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote

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


def _image_input(req: JobRequest) -> str | None:
    for key in (
        "image_url",
        "start_image_url",
        "image",
        "media",
        "input_image",
        "first_frame_url",
    ):
        value = req.inputs.get(key)
        if isinstance(value, str) and value:
            return value
    urls = req.inputs.get("image_urls")
    if isinstance(urls, list) and urls and isinstance(urls[0], str):
        return urls[0]
    return None


def _media_urls(payload: Any) -> list[str]:
    found: list[str] = []
    skip = {"status_url", "response_url", "cancel_url", "urls"}

    def walk(obj: Any, key: str | None = None) -> None:
        if key in skip:
            return
        if isinstance(obj, str) and obj.startswith(("http://", "https://")):
            found.append(obj)
        elif isinstance(obj, dict):
            for nested_key, value in obj.items():
                walk(value, str(nested_key))
        elif isinstance(obj, list):
            for value in obj:
                walk(value, key)

    walk(payload)
    out: list[str] = []
    seen: set[str] = set()
    for url in found:
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


class FalProvider(CatalogBackedProvider):
    catalog_name = "fal"
    provider_id = "fal"
    secret_name = "FAL_KEY"
    manifest = ProviderManifest(
        id="fal",
        display_name="fal",
        auth=ProviderAuth(env_vars=["FAL_KEY"]),
        docs_url="https://docs.fal.ai",
    )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Key {self._api_key}",
            "Content-Type": "application/json",
        }

    def _queue(self) -> str:
        return os.environ.get("FAL_QUEUE_URL", "https://queue.fal.run").rstrip("/")

    def _submit_live(self, req: JobRequest, spec: ModelSpec) -> ProviderJobRef:
        endpoint = self._catalog.endpoint_for(spec.id)
        if not endpoint:
            raise ValueError(f"no endpoint mapping for {spec.id}")
        url = f"{self._queue()}/{endpoint}"
        text = str(req.inputs.get("prompt") or req.inputs.get("text") or "")
        payload: dict[str, Any] = {}
        if "/tts/" in endpoint or "text-to-speech" in endpoint:
            payload["text"] = text
            if req.inputs.get("voice"):
                payload["voice"] = req.inputs["voice"]
        else:
            payload["prompt"] = self.prompt_text(req)
        image = _image_input(req)
        if image:
            if endpoint.endswith("/edit"):
                payload["image_urls"] = [image]
            elif "kling-video/v2.6" in endpoint and "image-to-video" in endpoint:
                payload["start_image_url"] = image
            elif "upscale" in endpoint or "image-to-video" in endpoint:
                payload["image_url"] = image
                if req.inputs.get("tail_image_url") or req.inputs.get("last_frame_url"):
                    payload["tail_image_url"] = str(
                        req.inputs.get("tail_image_url") or req.inputs.get("last_frame_url")
                    )
        duration = req.inputs.get("duration")
        if duration and "video" in endpoint:
            payload["duration"] = str(duration)
        aspect = req.inputs.get("aspect_ratio")
        if aspect:
            payload["aspect_ratio"] = str(aspect)
        body = self._post_json(url, self._headers(), payload)
        request_id = str(body.get("request_id") or body.get("id") or "")
        if not request_id:
            raise RuntimeError("fal submit missing job id")
        return ProviderJobRef(provider="fal", ref=f"{endpoint}#{request_id}")

    def _status_live(self, ref: ProviderJobRef) -> JobStatus | None:
        endpoint, _, request_id = ref.ref.rpartition("#")
        if not request_id:
            return None
        encoded = quote(request_id, safe="-._~")
        status_url = f"{self._queue()}/{endpoint}/requests/{encoded}/status"
        body = self._get_json(status_url, self._headers())
        raw = str(body.get("status") or "").upper()
        if raw in {"IN_QUEUE"}:
            state = JobState.QUEUED
        elif raw in {"IN_PROGRESS"}:
            state = JobState.RUNNING
        elif raw in {"COMPLETED"}:
            state = JobState.COMPLETED
        elif raw in {"CANCELED", "CANCELLED"}:
            state = JobState.CANCELLED
        elif raw in {"FAILED"}:
            return JobStatus(
                state=JobState.FAILED,
                error=VinciError(code=ErrorCode.UNKNOWN, message="failed", retryable=True),
            )
        else:
            state = JobState.RUNNING
        outputs: list[str] = []
        if state == JobState.COMPLETED:
            result_url = f"{self._queue()}/{endpoint}/requests/{encoded}"
            result = self._get_json(result_url, self._headers())
            outputs = _media_urls(result)
            progress = 1.0
        elif state == JobState.RUNNING:
            progress = 0.5
        else:
            progress = 0.1
        return JobStatus(state=state, outputs=outputs, progress=progress)
