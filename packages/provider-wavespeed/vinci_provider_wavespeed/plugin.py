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
        "image",
        "media",
        "image_url",
        "first_frame_url",
        "start_image_url",
    ):
        value = req.inputs.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    return None


class WavespeedProvider(CatalogBackedProvider):
    catalog_name = "wavespeed"
    provider_id = "wavespeed"
    secret_name = "WAVESPEED_API_KEY"
    manifest = ProviderManifest(
        id="wavespeed",
        display_name="Wavespeed",
        auth=ProviderAuth(env_vars=["WAVESPEED_API_KEY"]),
        docs_url="https://wavespeed.ai/docs",
    )

    def __init__(self, api_key: str | None = None, *, cas: Any | None = None) -> None:
        super().__init__(api_key=api_key)
        self._cas = cas

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _base(self) -> str:
        return os.environ.get("WAVESPEED_API_URL", "https://" + "api.wavespeed.ai").rstrip("/")

    def _submit_live(self, req: JobRequest, spec: ModelSpec) -> ProviderJobRef:
        endpoint = self._catalog.endpoint_for(spec.id)
        if not endpoint:
            raise ValueError(f"no endpoint mapping for {spec.id}")
        url = f"{self._base()}/api/v3/{endpoint}"
        payload: dict[str, Any] = {}
        if endpoint.endswith("seedvr2/image"):
            image = self._provider_image(_image_input(req))
            if not image:
                raise ValueError("seedvr2 image upscale needs a still")
            target = str(
                req.inputs.get("resolution") or req.inputs.get("target_resolution") or "4k"
            ).lower()
            if target not in {"2k", "4k", "8k"}:
                target = "4k"
            payload["image"] = image
            payload["target_resolution"] = target
        else:
            payload["prompt"] = self.prompt_text(req)
            image = self._provider_image(_image_input(req))
            if image:
                payload["image"] = image
            last = req.inputs.get("last_frame_url") or req.inputs.get("tail_image_url")
            if isinstance(last, str) and last:
                payload["last_image"] = self._provider_image(last) or last
            duration = _as_int(req.inputs.get("duration"))
            if duration is not None:
                payload["duration"] = duration
            aspect = req.inputs.get("aspect_ratio")
            if aspect:
                payload["aspect_ratio"] = str(aspect)
            size = req.inputs.get("size") or req.inputs.get("resolution")
            if size:
                payload["size"] = str(size).replace("x", "*").replace("×", "*")
        body = self._post_json(url, self._headers(), payload)
        ref = str(body.get("id") or body.get("request_id") or "")
        data = body.get("data")
        if not ref and isinstance(data, dict):
            ref = str(data.get("id") or "")
        if not ref:
            raise RuntimeError("wavespeed submit missing job id")
        return ProviderJobRef(provider="wavespeed", ref=ref)

    def _provider_image(self, value: str | None) -> str | None:
        """Turn a local asset id into a Wavespeed download URL.

        Image-to-video rejects a content digest. Public URLs pass through.
        """
        if not value or value.startswith(("http://", "https://", "data:")):
            return value
        cas = self._cas
        if cas is None or not cas.exists(value):
            return value
        blob = cas.get(value)
        from vinci_provider_sdk.local_image import sniff_media_mime

        mime = sniff_media_mime(blob)
        ext = {
            "image/png": "png",
            "image/jpeg": "jpg",
            "image/webp": "webp",
            "image/gif": "gif",
            "video/mp4": "mp4",
        }.get(mime or "")
        if mime is None or ext is None:
            raise ValueError("unsupported local media format")
        import urllib.request

        headers = self._headers()
        headers["Content-Type"] = mime
        headers["file"] = f"still.{ext}"
        request = urllib.request.Request(
            f"{self._base()}/api/v3/media/upload/binary",
            data=blob,
            headers=headers,
            method="POST",
        )
        body = self._open_json(request)
        data = body.get("data") if isinstance(body.get("data"), dict) else body
        download = data.get("download_url") if isinstance(data, dict) else None
        if not isinstance(download, str) or not download.startswith("https://"):
            raise RuntimeError("wavespeed upload missing download_url")
        return download

    def _status_live(self, ref: ProviderJobRef) -> JobStatus | None:
        task_id = ref.ref.strip()
        if not task_id:
            return None
        url = f"{self._base()}/api/v3/predictions/{quote(task_id, safe='-._~')}/result"
        body = self._get_json(url, self._headers())
        data = body.get("data") if isinstance(body.get("data"), dict) else body
        raw = str((data or {}).get("status") or "").lower()
        if raw in {"created"}:
            state = JobState.QUEUED
        elif raw in {"processing"}:
            state = JobState.RUNNING
        elif raw in {"completed"}:
            state = JobState.COMPLETED
        elif raw in {"cancelled", "canceled"}:
            state = JobState.CANCELLED
        elif raw in {"failed", "timeout", "deleted"}:
            return JobStatus(
                state=JobState.FAILED,
                error=VinciError(
                    code=ErrorCode.UNKNOWN,
                    message=str((data or {}).get("error") or raw),
                    retryable=raw in {"timeout"},
                ),
            )
        else:
            state = JobState.RUNNING
        outputs: list[str] = []
        for item in (data or {}).get("outputs") or []:
            if isinstance(item, str) and item:
                outputs.append(item)
            elif isinstance(item, dict):
                for key in ("url", "image", "video"):
                    if item.get(key):
                        outputs.append(str(item[key]))
                        break
        if state == JobState.COMPLETED:
            progress = 1.0
        elif state == JobState.RUNNING:
            progress = 0.5
        else:
            progress = 0.1
        return JobStatus(state=state, outputs=outputs, progress=progress)
