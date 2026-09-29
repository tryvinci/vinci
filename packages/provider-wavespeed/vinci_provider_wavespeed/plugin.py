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
        payload: dict[str, Any] = {"prompt": self.prompt_text(req)}
        image = _image_input(req)
        if image:
            payload["image"] = image
        last = req.inputs.get("last_frame_url") or req.inputs.get("tail_image_url")
        if isinstance(last, str) and last:
            payload["last_image"] = last
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
