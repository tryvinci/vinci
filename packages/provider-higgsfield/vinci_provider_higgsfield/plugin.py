from __future__ import annotations

import os
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


def _image_input(req: JobRequest) -> str | None:
    for key in ("image_url", "image", "media", "first_frame_url", "start_image_url"):
        value = req.inputs.get(key)
        if isinstance(value, str) and value:
            return value
    return None


class HiggsfieldProvider(CatalogBackedProvider):
    """First-class Higgsfield REST plugin. Auth is key + secret, not MCP."""

    catalog_name = "higgsfield"
    provider_id = "higgsfield"
    secret_name = "HIGGSFIELD_API_KEY"
    extra_secret_name = "HIGGSFIELD_API_SECRET"
    manifest = ProviderManifest(
        id="higgsfield",
        display_name="Higgsfield",
        auth=ProviderAuth(env_vars=["HIGGSFIELD_API_KEY", "HIGGSFIELD_API_SECRET"]),
        docs_url="https://docs.higgsfield.ai",
    )

    def __init__(self, api_key: str | None = None, api_secret: str | None = None) -> None:
        super().__init__(api_key=api_key)
        if api_secret:
            self._extra_secrets[self.extra_secret_name] = api_secret
        self._api_secret = api_secret

    def submit(self, req: JobRequest) -> ProviderJobRef:
        if not self._api_secret:
            raise PermissionError(f"missing {self.extra_secret_name}")
        return super().submit(req)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Key {self._api_key}:{self._api_secret}",
            "Content-Type": "application/json",
        }

    def _base(self) -> str:
        return os.environ.get("HIGGSFIELD_API_URL", "https://api.higgsfield.ai").rstrip("/")

    def _submit_live(self, req: JobRequest, spec: ModelSpec) -> ProviderJobRef:
        endpoint = self._catalog.endpoint_for(spec.id)
        if not endpoint:
            raise ValueError(f"no endpoint mapping for {spec.id}")
        url = f"{self._base()}{endpoint}"
        payload: dict[str, Any] = {"prompt": self.prompt_text(req)}
        image = _image_input(req)
        caps = {cap.value for cap in spec.capabilities}
        duration = req.inputs.get("duration")
        if duration and ("t2v" in caps or "i2v" in caps):
            payload["duration"] = str(duration)
        aspect = req.inputs.get("aspect_ratio")
        if aspect:
            payload["aspect_ratio"] = str(aspect)
        resolution = req.inputs.get("resolution")
        if resolution:
            payload["resolution"] = str(resolution)
        if "popcorn" in endpoint:
            raw_n = req.inputs.get("num_images") or req.inputs.get("frames") or 4
            try:
                payload["num_images"] = max(1, min(8, int(raw_n)))
            except (TypeError, ValueError):
                payload["num_images"] = 4
            urls = req.inputs.get("image_urls")
            if isinstance(urls, list) and urls:
                payload["image_urls"] = [str(item) for item in urls if item][:8]
            elif image:
                payload["image_urls"] = [image]
        elif "first-last-frame" in endpoint:
            first = req.inputs.get("first_frame_url") or req.inputs.get("start_image_url") or image
            last = req.inputs.get("last_frame_url") or req.inputs.get("tail_image_url") or image
            payload["first_frame_url"] = str(first or "")
            payload["last_frame_url"] = str(last or "")
        elif image and ("i2i" in caps or "i2v" in caps or "edit_multi" in caps):
            payload["image_url"] = image
        body = self._post_json(url, self._headers(), payload)
        ref = str(body.get("request_id") or body.get("id") or "")
        if not ref:
            raise RuntimeError("higgsfield submit missing request_id")
        return ProviderJobRef(provider="higgsfield", ref=ref)

    def _status_live(self, ref: ProviderJobRef) -> JobStatus | None:
        url = f"{self._base()}/requests/{ref.ref}/status"
        body = self._get_json(url, self._headers())
        raw = str(body.get("status") or "").lower()
        if raw in {"queued"}:
            state = JobState.QUEUED
        elif raw in {"in_progress"}:
            state = JobState.RUNNING
        elif raw in {"completed"}:
            state = JobState.COMPLETED
        elif raw in {"canceled", "cancelled"}:
            state = JobState.CANCELLED
        elif raw in {"nsfw"}:
            return JobStatus(
                state=JobState.FAILED,
                error=VinciError(code=ErrorCode.CONTENT_POLICY, message="nsfw", retryable=False),
            )
        elif raw in {"failed"}:
            return JobStatus(
                state=JobState.FAILED,
                error=VinciError(
                    code=ErrorCode.UNKNOWN,
                    message=str(body.get("error") or "failed"),
                    retryable=True,
                ),
            )
        else:
            state = JobState.RUNNING
        outputs: list[str] = []
        for item in body.get("images") or []:
            if isinstance(item, dict) and item.get("url"):
                outputs.append(str(item["url"]))
        video = body.get("video")
        if isinstance(video, dict) and video.get("url"):
            outputs.append(str(video["url"]))
        if state == JobState.COMPLETED:
            progress = 1.0
        elif state == JobState.RUNNING:
            progress = 0.5
        else:
            progress = 0.1
        return JobStatus(state=state, outputs=outputs, progress=progress)

    def cancel(self, ref: ProviderJobRef) -> None:
        try:
            self._post_json(f"{self._base()}/requests/{ref.ref}/cancel", self._headers(), {})
        except Exception:  # noqa: BLE001 — cancel is best-effort
            pass
        super().cancel(ref)
