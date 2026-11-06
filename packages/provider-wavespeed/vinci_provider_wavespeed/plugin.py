from __future__ import annotations

import math
import os
from typing import Any
from urllib.parse import quote

from vinci_core.cost import estimate_from_spec, idempotency_key, resolve_model
from vinci_protocol.enums import ErrorCode, JobState
from vinci_protocol.models import (
    Estimate,
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


# InfiniteTalk bills per second (720p $0.06, 480p $0.03), minimum 3s, cap 10 minutes.
# https://wavespeed.ai/docs/docs-api/wavespeed-ai/infinitetalk
_TALK_MODEL = "wavespeed:infinitetalk:2026-08"
_TALK_PER_SEC = {"480p": 0.03, "720p": 0.06}
# Layer3 bitrate index -> kbps. Index 0 and 15 are invalid. MPEG-2.5 matches MPEG2.
_MP3_KBPS = {
    (3, 1): [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0],
    (2, 1): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0],
    (0, 1): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0],
}
# Version 3 is MPEG1, version 2 is MPEG2, version 0 is MPEG-2.5. Index 3 is reserved.
_MP3_RATE = {3: [44100, 48000, 32000], 2: [22050, 24000, 16000], 0: [11025, 12000, 8000]}


def _talk_tier(resolution: Any) -> str:
    if resolution == "480p":
        return "480p"
    return "720p"


def _wav_seconds(blob: bytes) -> float | None:
    if len(blob) < 12 or blob[:4] != b"RIFF" or blob[8:12] != b"WAVE":
        return None
    pos = 12
    byte_rate = 0
    data_size = 0
    while pos + 8 <= len(blob):
        kind = blob[pos : pos + 4]
        size = int.from_bytes(blob[pos + 4 : pos + 8], "little")
        data = blob[pos + 8 : pos + 8 + size]
        if kind == b"fmt " and len(data) >= 12:
            byte_rate = int.from_bytes(data[8:12], "little")
        elif kind == b"data":
            data_size = size
        pos += 8 + size + (size % 2)
    if byte_rate <= 0 or data_size <= 0:
        return None
    return data_size / byte_rate


def _mp3_frame(blob: bytes, i: int) -> tuple[int, int, int] | None:
    """One MPEG layer3 frame: byte length, sample count, and sample rate."""
    if i + 4 > len(blob) or blob[i] != 0xFF or blob[i + 1] & 0xE0 != 0xE0:
        return None
    version = (blob[i + 1] >> 3) & 0x3
    layer = (blob[i + 1] >> 1) & 0x3
    bitrate_index = (blob[i + 2] >> 4) & 0xF
    sample_index = (blob[i + 2] >> 2) & 0x3
    padding = (blob[i + 2] >> 1) & 0x1
    rates = _MP3_KBPS.get((version, layer))
    sample_rates = _MP3_RATE.get(version)
    if rates is None or sample_rates is None or sample_index > 2 or bitrate_index in {0, 15}:
        return None
    kbps = rates[bitrate_index]
    sample_rate = sample_rates[sample_index]
    if kbps <= 0:
        return None
    samples = 1152 if version == 3 else 576
    scale = 144 if version == 3 else 72
    size = scale * kbps * 1000 // sample_rate + padding
    if size < 4 or i + size > len(blob):
        return None
    return size, samples, sample_rate


def _mp3_seconds(blob: bytes) -> float | None:
    """Sum each layer3 frame. A later frame can use a different bitrate."""
    start = 0
    if blob[:3] == b"ID3" and len(blob) >= 10:
        words = blob[6:10]
        size = (
            ((words[0] & 0x7F) << 21)
            | ((words[1] & 0x7F) << 14)
            | ((words[2] & 0x7F) << 7)
            | (words[3] & 0x7F)
        )
        start = 10 + size
    end = min(len(blob) - 4, start + 4096)
    pos = next((i for i in range(start, max(start, end)) if _mp3_frame(blob, i)), None)
    if pos is None:
        return None
    seconds = 0.0
    # Past 600s the bill is capped, so stop reading.
    while seconds < 600:
        frame = _mp3_frame(blob, pos)
        if frame is None:
            break
        size, samples, rate = frame
        seconds += samples / rate
        pos += size
    return seconds or None


def _hint_number(value: Any) -> float | None:
    """Parsed duration hint. ``None`` when it is absent or not a number."""
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _hint_seconds(value: Any) -> int | None:
    """Positive duration hint in whole seconds. ``0.5`` becomes ``1``."""
    number = _hint_number(value)
    if number is None or not math.isfinite(number) or number <= 0:
        return None
    return math.ceil(number)


def _remote_audio(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(("http://", "https://", "data:"))


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

    def estimate(self, req: JobRequest) -> Estimate:
        spec = resolve_model(self._catalog, req)
        if spec.id != _TALK_MODEL:
            return super().estimate(req)
        key = req.idempotency_key or idempotency_key(spec.id, req.inputs)
        tier = _talk_tier(req.inputs.get("resolution"))
        audio = req.inputs.get("audio")
        # The submit sends the audio and no duration, so a local file wins over a hint.
        heard = self._local_audio_seconds(audio)
        hint = req.inputs.get("duration")
        hint_number = _hint_number(hint)
        seconds = math.ceil(heard) if heard else _hint_seconds(hint)
        # Zero, NaN, and infinity are not lengths. A missing hint is rejected
        # only when a store is configured.
        bad_hint = hint_number is not None and (
            not math.isfinite(hint_number) or hint_number <= 0
        )
        remote_unpriced = _remote_audio(audio) and not heard and (
            bad_hint or (seconds is None and self._cas is not None)
        )
        if remote_unpriced:
            raise ValueError(
                "infinitetalk needs a positive duration when the audio is a remote URL"
            )
        self._estimated.add(key)
        # Unknown local audio prices one 5s block. A known length uses the documented 3s minimum.
        billed = 5 if seconds is None else min(600, max(3, seconds))
        amount = _TALK_PER_SEC[tier] * billed
        base = estimate_from_spec(spec, billed / 5)
        return base.model_copy(update={"amount": amount, "unit_count": billed / 5})

    def _local_audio_seconds(self, value: Any) -> float | None:
        # A URL is not a digest. The local store raises ValueError on it.
        if (
            not isinstance(value, str)
            or not value
            or value.startswith(("http://", "https://", "data:"))
            or self._cas is None
        ):
            return None
        if not self._cas.exists(value):
            return None
        blob = self._cas.get(value)
        return _wav_seconds(blob) or _mp3_seconds(blob)

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
        elif endpoint == "wavespeed-ai/infinitetalk":
            # InfiniteTalk lip-syncs a still or a video to `audio`; video has its own v2v route.
            audio = self._provider_image(req.inputs.get("audio"))
            if not audio:
                raise ValueError("infinitetalk needs an audio track")
            video = req.inputs.get("video")
            if isinstance(video, str) and video:
                url += "/video-to-video"
                payload["video"] = self._provider_image(video)
            else:
                image = self._provider_image(_image_input(req))
                if not image:
                    raise ValueError("infinitetalk needs a still or a video")
                payload["image"] = image
            payload["audio"] = audio
            prompt = req.inputs.get("prompt")
            if isinstance(prompt, str) and prompt.strip():
                payload["prompt"] = prompt.strip()
            # Studio's catalog lists this model as 1280x720; Wavespeed wants 480p or 720p.
            # An omitted resolution is the displayed 720p default, not Wavespeed's 480p.
            resolution = req.inputs.get("resolution")
            if resolution in {None, "", "1280x720"}:
                resolution = "720p"
            if resolution in {"480p", "720p"}:
                payload["resolution"] = resolution
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
            "audio/mpeg": "mp3",
            "audio/wav": "wav",
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
