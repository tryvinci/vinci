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
    for key in ("image", "media", "image_url", "input_image"):
        value = req.inputs.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _task_id(body: dict[str, Any]) -> str:
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    for blob in (body, data if isinstance(data, dict) else {}):
        for key in ("task_id", "id"):
            value = blob.get(key)
            if value:
                return str(value)
    return ""


class MagnificProvider(CatalogBackedProvider):
    """First-class Magnific REST plugin. Header x-magnific-api-key. Not MCP."""

    catalog_name = "magnific"
    provider_id = "magnific"
    secret_name = "MAGNIFIC_API_KEY"
    manifest = ProviderManifest(
        id="magnific",
        display_name="Magnific / Freepik",
        auth=ProviderAuth(env_vars=["MAGNIFIC_API_KEY"]),
        docs_url="https://docs.magnific.com/introduction",
    )

    def _headers(self) -> dict[str, str]:
        return {
            "x-magnific-api-key": str(self._api_key),
            "Content-Type": "application/json",
        }

    def _base(self) -> str:
        return os.environ.get("MAGNIFIC_API_URL", "https://api.magnific.com").rstrip("/")

    def _submit_live(self, req: JobRequest, spec: ModelSpec) -> ProviderJobRef:
        endpoint = self._catalog.endpoint_for(spec.id)
        if not endpoint:
            raise ValueError(f"no endpoint mapping for {spec.id}")
        url = f"{self._base()}{endpoint}"
        prompt = self.prompt_text(req)
        image = _image_input(req)
        payload: dict[str, Any] = {"prompt": prompt}
        aspect = req.inputs.get("aspect_ratio")
        if aspect:
            payload["aspect_ratio"] = str(aspect)
        duration = req.inputs.get("duration")
        videoish = any(
            token in endpoint
            for token in (
                "kling",
                "image-to-video",
                "text-to-video",
                "/video/",
                "hailuo",
                "seedance",
            )
        )
        if "video-upscaler" in endpoint:
            if not image:
                raise ValueError("magnific upscaler needs a clip")
            payload["video"] = image
        elif "upscaler" in endpoint:
            if not image:
                raise ValueError("magnific upscaler needs an image")
            payload["image"] = image
            payload["scale_factor"] = str(req.inputs.get("scale") or "4x")
            if "precision" not in endpoint:
                for key in ("creativity", "resemblance", "hdr", "fractality"):
                    raw = req.inputs.get(key)
                    if raw in (None, ""):
                        continue
                    text = str(raw)
                    if "{{" in text:
                        continue
                    payload[key] = int(raw)
                style = req.inputs.get("optimized_for")
                if style and "{{" not in str(style):
                    payload["optimized_for"] = str(style)
                engine = req.inputs.get("engine")
                if engine and "{{" not in str(engine):
                    payload["engine"] = str(engine)
        elif videoish:
            if duration:
                payload["duration"] = str(int(duration))
            elif "kling" in endpoint:
                payload["duration"] = "5"
            if image:
                payload["image"] = image
        elif image and ("edit" in endpoint or "seedream" in endpoint or "nano-banana" in endpoint):
            payload["image"] = image
        elif "flux" in endpoint and image:
            payload["input_image"] = image
        body = self._post_json(url, self._headers(), payload)
        ref = _task_id(body)
        if not ref:
            raise RuntimeError("magnific submit missing task_id")
        return ProviderJobRef(provider="magnific", ref=f"{endpoint}#{ref}")

    def _status_path(self, endpoint: str) -> str:
        # Kling 3.0 Turbo generate paths are resolution-suffixed; status is the unsuffixed route.
        if "kling-v3-turbo" in endpoint:
            for suffix in ("-1080p", "-720p", "-480p"):
                if endpoint.endswith(suffix):
                    return endpoint[: -len(suffix)]
        return endpoint

    def _status_live(self, ref: ProviderJobRef) -> JobStatus | None:
        endpoint, _, task_id = ref.ref.partition("#")
        if not task_id:
            task_id = ref.ref
            endpoint = "/v1/ai/mystic"
        url = f"{self._base()}{self._status_path(endpoint)}/{task_id}"
        body = self._get_json(url, self._headers())
        data = body.get("data") if isinstance(body.get("data"), dict) else body
        raw = str((data or {}).get("status") or "").upper()
        if raw in {"CREATED"}:
            state = JobState.QUEUED
        elif raw in {"IN_PROGRESS"}:
            state = JobState.RUNNING
        elif raw in {"COMPLETED"}:
            state = JobState.COMPLETED
        elif raw in {"FAILED"}:
            return JobStatus(
                state=JobState.FAILED,
                error=VinciError(code=ErrorCode.UNKNOWN, message="failed", retryable=True),
            )
        else:
            state = JobState.RUNNING
        outputs: list[str] = []
        generated = (data or {}).get("generated") or []
        if isinstance(generated, list):
            outputs.extend(str(item) for item in generated if item)
        if state == JobState.COMPLETED:
            progress = 1.0
        elif state == JobState.RUNNING:
            progress = 0.5
        else:
            progress = 0.1
        return JobStatus(state=state, outputs=outputs, progress=progress)
