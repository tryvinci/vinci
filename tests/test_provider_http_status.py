from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pytest
from vinci_core.catalog import load_bundled_catalog
from vinci_protocol.enums import AssetKind, Capability, ErrorCode, JobState
from vinci_protocol.models import JobRequest, JobStatus, ProviderJobRef
from vinci_provider_elevenlabs import ElevenLabsProvider
from vinci_provider_fal import FalProvider
from vinci_provider_google import GoogleProvider
from vinci_provider_higgsfield import HiggsfieldProvider
from vinci_provider_magnific import MagnificProvider
from vinci_provider_sdk.mock import png_scene
from vinci_provider_wavespeed import WavespeedProvider
from vinci_runtime.engine import Engine


class _FakeResp:
    def __init__(self, payload: dict[str, Any] | bytes) -> None:
        self._raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._raw

    def __enter__(self) -> _FakeResp:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_higgsfield_catalog_matches_public_openapi_paths() -> None:
    catalog = load_bundled_catalog("higgsfield")
    endpoints = catalog.endpoints
    assert endpoints["higgsfield:soul-standard:2026-09"] == "/higgsfield-ai/soul/standard"
    assert endpoints["higgsfield:dop-lite:2026-09"] == "/higgsfield-ai/dop/lite"
    assert endpoints["higgsfield:veo-3.1-fast-i2v:2026-09"] == "/veo3.1/fast/image-to-video"
    assert endpoints["higgsfield:wan-25-i2v:2026-09"] == "/wan-25-preview/image-to-video"
    assert (
        endpoints["higgsfield:seedance-lite-i2v:2026-09"]
        == "/bytedance/seedance/v1/lite/image-to-video"
    )
    assert (
        endpoints["higgsfield:seedance-pro-fast-i2v:2026-09"]
        == "/bytedance/seedance/v1/pro/fast/image-to-video"
    )
    assert endpoints["higgsfield:veo-3.1-flf:2026-09"] == "/veo3.1/first-last-frame-to-video"
    assert (
        endpoints["higgsfield:veo-3.1-fast-flf:2026-09"]
        == "/veo3.1/fast/first-last-frame-to-video"
    )
    assert endpoints["higgsfield:popcorn-auto:2026-09"] == "/higgsfield-ai/popcorn/auto"
    popcorn = next(m for m in catalog.models if m.id == "higgsfield:popcorn-auto:2026-09")
    assert {cap.value for cap in popcorn.capabilities} == {"t2i", "i2i"}
    assert popcorn.pricing.unit == "image"
    assert not any("sora" in model.id.lower() for model in catalog.models)
    assert not any("sora" in path.lower() for path in endpoints.values())


def test_magnific_catalog_matches_public_api_paths() -> None:
    catalog = load_bundled_catalog("magnific")
    endpoints = catalog.endpoints
    assert endpoints["magnific:mystic:2026-09"] == "/v1/ai/mystic"
    assert endpoints["magnific:flux-2-turbo:2026-09"] == "/v1/ai/text-to-image/flux-2-turbo"
    assert endpoints["magnific:seedream-4.5:2026-09"] == "/v1/ai/text-to-image/seedream-v4-5"
    assert endpoints["magnific:wan-2.5-i2v:2026-09"] == "/v1/ai/image-to-video/wan-2-5-i2v-1080p"
    assert endpoints["magnific:seedream-5-pro:2026-09"] == "/v1/ai/text-to-image/seedream-v5-pro"
    assert endpoints["magnific:kling-3-pro:2026-09"] == "/v1/ai/video/kling-v3-pro"
    assert (
        endpoints["magnific:kling-3-turbo-i2v-1080p:2026-09"]
        == "/v1/ai/image-to-video/kling-v3-turbo-1080p"
    )
    assert endpoints["magnific:wan-2.6-i2v:2026-09"] == "/v1/ai/image-to-video/wan-v2-6-1080p"
    assert endpoints["magnific:wan-2.7-t2v:2026-09"] == "/v1/ai/text-to-video/wan-2-7"
    assert endpoints["magnific:upscaler-creative:2026-09"] == "/v1/ai/image-upscaler"
    creative = next(m for m in catalog.models if m.id == "magnific:upscaler-creative:2026-09")
    assert creative.constraints.resolutions == ["2x", "4x", "8x", "16x"]


def test_fal_catalog_matches_public_app_ids() -> None:
    catalog = load_bundled_catalog("fal")
    endpoints = catalog.endpoints
    assert endpoints["fal:flux-schnell:2026-08"] == "fal-ai/flux/schnell"
    assert endpoints["fal:nano-banana-pro:2026-09"] == "fal-ai/nano-banana-pro"
    assert (
        endpoints["fal:kling-2.6-pro-i2v:2026-09"]
        == "fal-ai/kling-video/v2.6/pro/image-to-video"
    )
    assert (
        endpoints["fal:seedance-1.5-pro-i2v:2026-09"]
        == "fal-ai/bytedance/seedance/v1.5/pro/image-to-video"
    )
    assert endpoints["fal:veo-3.1-fast-i2v:2026-09"] == "fal-ai/veo3.1/fast/image-to-video"
    assert endpoints["fal:elevenlabs-tts-v3:2026-09"] == "fal-ai/elevenlabs/tts/eleven-v3"
    assert not any("sora" in model.id.lower() for model in catalog.models)


def test_wavespeed_catalog_matches_public_api_paths() -> None:
    catalog = load_bundled_catalog("wavespeed")
    endpoints = catalog.endpoints
    assert endpoints["wavespeed:kling-2.6-pro:2026-08"] == "kwaivgi/kling-v2.6-pro/text-to-video"
    assert (
        endpoints["wavespeed:kling-3-turbo-pro-i2v:2026-09"]
        == "kwaivgi/kling-v3-turbo-pro/image-to-video"
    )
    assert endpoints["wavespeed:nano-banana-pro:2026-09"] == "google/nano-banana-pro/text-to-image"
    assert endpoints["wavespeed:hailuo-2.3-t2v:2026-09"] == "minimax/hailuo-2.3/t2v-standard"
    assert endpoints["wavespeed:hailuo-2.3-fast-pro:2026-09"] == "minimax/hailuo-2.3/fast-pro"
    assert (
        endpoints["wavespeed:seedance-2.0-i2v:2026-09"]
        == "bytedance/seedance-2.0/image-to-video"
    )
    assert endpoints["wavespeed:seedvr2:2026-08"] == "wavespeed-ai/seedvr2/image"
    assert not any("sora" in model.id.lower() for model in catalog.models)


def test_wavespeed_seedvr2_image_uses_target_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VINCI_ALLOW_LIVE_SPEND", "1")
    png = b"\x89PNG\r\n\x1a\n" + b"still"
    provider = WavespeedProvider(api_key="ws-key", cas=_mem_cas({"still": png}))
    seen: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: int = 30) -> _FakeResp:
        if request.full_url.endswith("/media/upload/binary"):
            return _FakeResp({"data": {"download_url": "https://cdn.example/still.png"}})
        seen["url"] = request.full_url
        seen["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResp({"data": {"id": "up-1"}})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    req = JobRequest(
        capability=Capability.UPSCALE,
        model_id="wavespeed:seedvr2:2026-08",
        inputs={"media": "still", "resolution": "4k"},
    )
    provider.estimate(req)
    ref = provider.submit(req)
    assert ref.ref == "up-1"
    assert seen["url"].endswith("/wavespeed-ai/seedvr2/image")
    assert seen["body"] == {"image": "https://cdn.example/still.png", "target_resolution": "4k"}


def test_higgsfield_status_live_completed(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = HiggsfieldProvider(api_key="key-id", api_secret="key-secret")
    seen: dict[str, str] = {}

    def fake_urlopen(request: Any, timeout: int = 30) -> _FakeResp:
        seen["url"] = request.full_url
        headers = {str(k).lower(): str(v) for k, v in request.header_items()}
        seen["auth"] = headers.get("authorization", "")
        return _FakeResp(
            {
                "status": "completed",
                "images": [{"url": "https://cdn.example/still.png"}],
                "video": {"url": "https://cdn.example/clip.mp4"},
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    status = provider.status(ProviderJobRef(provider="higgsfield", ref="req-1"))
    assert seen["url"].endswith("/requests/req-1/status")
    assert seen["auth"] == "Key key-id:key-secret"
    assert status.state == JobState.COMPLETED
    assert status.outputs == ["https://cdn.example/still.png", "https://cdn.example/clip.mp4"]
    again = provider.status(ProviderJobRef(provider="higgsfield", ref="req-1"))
    assert again.state == JobState.COMPLETED


def test_higgsfield_status_nsfw_is_content_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = HiggsfieldProvider(api_key="key-id", api_secret="key-secret")
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout=30: _FakeResp({"status": "nsfw"}),
    )
    status = provider._status_live(ProviderJobRef(provider="higgsfield", ref="req-nsfw"))
    assert status is not None
    assert status.state == JobState.FAILED
    assert status.error is not None
    assert status.error.code == ErrorCode.CONTENT_POLICY


def test_higgsfield_status_polls_in_progress_then_completes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = HiggsfieldProvider(api_key="key-id", api_secret="key-secret")
    calls = {"n": 0}

    def fake_urlopen(request: Any, timeout: int = 30) -> _FakeResp:
        calls["n"] += 1
        if calls["n"] == 1:
            return _FakeResp({"status": "in_progress"})
        return _FakeResp({"status": "completed", "images": [{"url": "https://cdn.example/a.png"}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    ref = ProviderJobRef(provider="higgsfield", ref="req-poll")
    first = provider.status(ref)
    assert first.state == JobState.RUNNING
    second = provider.status(ref)
    assert second.state == JobState.COMPLETED
    third = provider.status(ref)
    assert third.state == JobState.COMPLETED
    assert calls["n"] == 2


def test_magnific_status_live_mystic_completed(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = MagnificProvider(api_key="mag-key")
    seen: dict[str, str] = {}

    def fake_urlopen(request: Any, timeout: int = 30) -> _FakeResp:
        seen["url"] = request.full_url
        headers = {str(k).lower(): str(v) for k, v in request.header_items()}
        seen["key"] = headers.get("x-magnific-api-key", "")
        return _FakeResp(
            {
                "data": {
                    "status": "COMPLETED",
                    "generated": ["https://cdn.example/mystic.png"],
                }
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    status = provider.status(
        ProviderJobRef(provider="magnific", ref="/v1/ai/mystic#task-9")
    )
    assert seen["url"].endswith("/v1/ai/mystic/task-9")
    assert seen["key"] == "mag-key"
    assert status.state == JobState.COMPLETED
    assert status.outputs == ["https://cdn.example/mystic.png"]


def test_wait_status_polls_until_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    monkeypatch.setenv("VINCI_JOB_POLL_INTERVAL", "0")
    engine = Engine(tmp_path)
    engine.init_home(demo=True)

    class _Polling:
        def __init__(self) -> None:
            self.n = 0

        def status(self, ref: ProviderJobRef) -> JobStatus:
            self.n += 1
            if self.n < 3:
                return JobStatus(state=JobState.QUEUED, outputs=[])
            return JobStatus(state=JobState.COMPLETED, outputs=["abc"])

    provider = _Polling()
    got = engine._wait_status(provider, ProviderJobRef(provider="mock", ref="x"))
    assert got.state == JobState.COMPLETED
    assert provider.n == 3


def test_wavespeed_status_live_completed(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = WavespeedProvider(api_key="ws-key")
    seen: dict[str, str] = {}

    def fake_urlopen(request: Any, timeout: int = 30) -> _FakeResp:
        seen["url"] = request.full_url
        headers = {str(k).lower(): str(v) for k, v in request.header_items()}
        seen["auth"] = headers.get("authorization", "")
        return _FakeResp(
            {
                "code": 200,
                "data": {
                    "id": "pred-1",
                    "status": "completed",
                    "outputs": ["https://cdn.example/wave.png"],
                },
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    status = provider.status(ProviderJobRef(provider="wavespeed", ref="pred-1"))
    assert seen["url"].endswith("/api/v3/predictions/pred-1/result")
    assert seen["auth"] == "Bearer ws-key"
    assert status.state == JobState.COMPLETED
    assert status.outputs == ["https://cdn.example/wave.png"]


def test_fal_submit_ref_and_status_fetches_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VINCI_ALLOW_LIVE_SPEND", "1")
    provider = FalProvider(api_key="fal-key")
    calls: list[str] = []

    def fake_urlopen(request: Any, timeout: int = 30) -> _FakeResp:
        url = request.full_url
        calls.append(url)
        headers = {str(k).lower(): str(v) for k, v in request.header_items()}
        assert headers.get("authorization") == "Key fal-key"
        if request.get_method() == "POST":
            return _FakeResp({"request_id": "req-flux"})
        if url.endswith("/status"):
            return _FakeResp({"status": "COMPLETED"})
        return _FakeResp({"images": [{"url": "https://cdn.example/flux.png"}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    req = JobRequest(
        capability=Capability.T2I,
        model_id="fal:flux-schnell:2026-08",
        inputs={"prompt": "flux still"},
    )
    provider.estimate(req)
    ref = provider.submit(req)
    assert ref.ref == "fal-ai/flux/schnell#req-flux"
    status = provider.status(ref)
    assert status.state == JobState.COMPLETED
    assert status.outputs == ["https://cdn.example/flux.png"]
    assert any(item.endswith("/requests/req-flux/status") for item in calls)
    assert any(
        item.endswith("/requests/req-flux") and not item.endswith("/status") for item in calls
    )


def test_fal_i2v_submit_sends_start_image_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VINCI_ALLOW_LIVE_SPEND", "1")
    provider = FalProvider(api_key="fal-key")
    seen: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: int = 30) -> _FakeResp:
        if request.get_method() == "POST":
            seen["url"] = request.full_url
            seen["body"] = json.loads(request.data.decode("utf-8"))
            return _FakeResp({"request_id": "req-kling"})
        return _FakeResp({"status": "IN_QUEUE"})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    req = JobRequest(
        capability=Capability.I2V,
        model_id="fal:kling-2.6-pro-i2v:2026-09",
        inputs={
            "prompt": "walk",
            "image_url": "https://cdn.example/start.png",
            "duration": "5",
        },
    )
    provider.estimate(req)
    ref = provider.submit(req)
    assert ref.ref == "fal-ai/kling-video/v2.6/pro/image-to-video#req-kling"
    assert seen["url"].endswith("/fal-ai/kling-video/v2.6/pro/image-to-video")
    assert seen["body"]["prompt"] == "walk"
    assert seen["body"]["start_image_url"] == "https://cdn.example/start.png"
    assert seen["body"]["duration"] == "5"


def test_higgsfield_flf_submit_sends_frame_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VINCI_ALLOW_LIVE_SPEND", "1")
    provider = HiggsfieldProvider(api_key="key-id", api_secret="key-secret")
    seen: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: int = 30) -> _FakeResp:
        seen["url"] = request.full_url
        seen["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResp({"request_id": "req-flf"})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    req = JobRequest(
        capability=Capability.I2V,
        model_id="higgsfield:veo-3.1-fast-flf:2026-09",
        inputs={
            "prompt": "cut between frames",
            "first_frame_url": "https://cdn.example/first.png",
            "last_frame_url": "https://cdn.example/last.png",
        },
    )
    provider.estimate(req)
    ref = provider.submit(req)
    assert ref.ref == "req-flf"
    assert seen["url"].endswith("/veo3.1/fast/first-last-frame-to-video")
    assert seen["body"]["first_frame_url"] == "https://cdn.example/first.png"
    assert seen["body"]["last_frame_url"] == "https://cdn.example/last.png"


def test_higgsfield_popcorn_submit_sends_num_images_and_image_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VINCI_ALLOW_LIVE_SPEND", "1")
    provider = HiggsfieldProvider(api_key="key-id", api_secret="key-secret")
    seen: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: int = 30) -> _FakeResp:
        seen["url"] = request.full_url
        seen["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResp({"request_id": "req-popcorn"})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    req = JobRequest(
        capability=Capability.T2I,
        model_id="higgsfield:popcorn-auto:2026-09",
        inputs={
            "prompt": "four beat sequence",
            "num_images": 4,
            "image": "https://cdn.example/ref.png",
            "aspect_ratio": "16:9",
            "resolution": "720p",
        },
    )
    provider.estimate(req)
    ref = provider.submit(req)
    assert ref.ref == "req-popcorn"
    assert seen["url"].endswith("/higgsfield-ai/popcorn/auto")
    assert seen["body"]["num_images"] == 4
    assert seen["body"]["image_urls"] == ["https://cdn.example/ref.png"]
    assert seen["body"]["aspect_ratio"] == "16:9"
    assert seen["body"]["resolution"] == "720p"
    assert "first_frame_url" not in seen["body"]


def test_wavespeed_i2v_submit_sends_duration_and_image(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VINCI_ALLOW_LIVE_SPEND", "1")
    provider = WavespeedProvider(api_key="ws-key")
    seen: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: int = 30) -> _FakeResp:
        seen["url"] = request.full_url
        seen["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResp({"data": {"id": "pred-i2v"}})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    req = JobRequest(
        capability=Capability.I2V,
        model_id="wavespeed:kling-3-turbo-pro-i2v:2026-09",
        inputs={
            "prompt": "walk",
            "image": "https://cdn.example/start.png",
            "duration": "5",
            "aspect_ratio": "9:16",
            "resolution": "1920x1080",
        },
    )
    provider.estimate(req)
    ref = provider.submit(req)
    assert ref.ref == "pred-i2v"
    assert seen["url"].endswith("/api/v3/kwaivgi/kling-v3-turbo-pro/image-to-video")
    assert seen["body"]["prompt"] == "walk"
    assert seen["body"]["image"] == "https://cdn.example/start.png"
    assert seen["body"]["duration"] == 5
    assert seen["body"]["aspect_ratio"] == "9:16"
    assert seen["body"]["size"] == "1920*1080"


def test_wavespeed_i2v_uploads_local_asset_before_submit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VINCI_ALLOW_LIVE_SPEND", "1")
    png = b"\x89PNG\r\n\x1a\n" + b"still"
    cas = type(
        "Cas",
        (),
        {
            "exists": lambda self, digest: digest == "abc",
            "get": lambda self, digest: png,
        },
    )()
    provider = WavespeedProvider(api_key="ws-key", cas=cas)
    seen: list[dict[str, Any]] = []

    def fake_urlopen(request: Any, timeout: int = 30) -> _FakeResp:
        seen.append({"url": request.full_url, "content_type": request.get_header("Content-type")})
        if request.full_url.endswith("/media/upload/binary"):
            return _FakeResp({"data": {"download_url": "https://cdn.example/uploaded.png"}})
        seen[-1]["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResp({"data": {"id": "pred-local"}})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    req = JobRequest(
        capability=Capability.I2V,
        model_id="wavespeed:kling-3-turbo-pro-i2v:2026-09",
        inputs={"prompt": "gentle breeze", "image": "abc"},
    )
    provider.estimate(req)
    ref = provider.submit(req)
    assert ref.ref == "pred-local"
    assert seen[0]["url"].endswith("/media/upload/binary")
    assert seen[0]["content_type"] == "image/png"
    assert seen[1]["body"]["image"] == "https://cdn.example/uploaded.png"
    assert seen[1]["body"]["prompt"] == "gentle breeze"


def _mem_cas(blobs: dict[str, bytes]) -> Any:
    return type(
        "Cas",
        (),
        {
            "exists": lambda self, digest: digest in blobs,
            "get": lambda self, digest: blobs[digest],
        },
    )()


def test_local_media_preserves_gif_and_video_and_rejects_unknown() -> None:
    from vinci_provider_sdk.local_image import as_data_uri, local_image_bytes

    png = b"\x89PNG\r\n\x1a\n" + b"png"
    gif = b"GIF89a" + b"gif"
    mp4 = b"\x00\x00\x00\x18ftypmp42" + b"mp4"
    heic = b"\x00\x00\x00\x18ftypheic" + b"\x00\x00\x00\x00mif1"
    avif = b"\x00\x00\x00\x14ftypavif" + b"\x00\x00\x00\x00"
    unknown = b"\x00\x00\x00\x0cftypXXXX"
    cas = _mem_cas(
        {
            "png": png,
            "gif": gif,
            "mp4": mp4,
            "heic": heic,
            "avif": avif,
            "bad": b"not-media",
            "ftyp": unknown,
        }
    )
    assert as_data_uri("gif", cas).startswith("data:image/gif;base64,")
    assert as_data_uri("mp4", cas).startswith("data:video/mp4;base64,")
    assert as_data_uri("heic", cas).startswith("data:image/heic;base64,")
    assert as_data_uri("avif", cas).startswith("data:image/avif;base64,")
    assert local_image_bytes("heic", cas)[1] == "image/heic"
    assert local_image_bytes("png", cas)[1] == "image/png"
    with pytest.raises(ValueError, match="unsupported local image"):
        local_image_bytes("mp4", cas)
    with pytest.raises(ValueError, match="unsupported local media"):
        as_data_uri("bad", cas)
    with pytest.raises(ValueError, match="unsupported local media"):
        as_data_uri("ftyp", cas)


def test_wavespeed_upload_keeps_gif_mime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VINCI_ALLOW_LIVE_SPEND", "1")
    gif = b"GIF89a" + b"still"
    provider = WavespeedProvider(api_key="ws-key", cas=_mem_cas({"gif": gif}))
    seen: list[dict[str, Any]] = []

    def fake_urlopen(request: Any, timeout: int = 30) -> _FakeResp:
        seen.append({"url": request.full_url, "content_type": request.get_header("Content-type")})
        if request.full_url.endswith("/media/upload/binary"):
            return _FakeResp({"data": {"download_url": "https://cdn.example/uploaded.gif"}})
        return _FakeResp({"data": {"id": "pred-gif"}})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    req = JobRequest(
        capability=Capability.I2V,
        model_id="wavespeed:kling-3-turbo-pro-i2v:2026-09",
        inputs={"prompt": "loop", "image": "gif"},
    )
    provider.estimate(req)
    provider.submit(req)
    assert seen[0]["content_type"] == "image/gif"


def test_wavespeed_rejects_unknown_local_media() -> None:
    provider = WavespeedProvider(api_key="ws-key", cas=_mem_cas({"bad": b"not-media"}))
    with pytest.raises(ValueError, match="unsupported local media"):
        provider._provider_image("bad")


def test_higgsfield_flf_resolves_local_frames(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VINCI_ALLOW_LIVE_SPEND", "1")
    first = b"\x89PNG\r\n\x1a\n" + b"first"
    last = b"GIF89a" + b"last"
    provider = HiggsfieldProvider(
        api_key="key-id",
        api_secret="key-secret",
        cas=_mem_cas({"first": first, "last": last}),
    )
    seen: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: int = 30) -> _FakeResp:
        seen["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResp({"request_id": "req-local-flf"})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    req = JobRequest(
        capability=Capability.I2V,
        model_id="higgsfield:veo-3.1-fast-flf:2026-09",
        inputs={"prompt": "cut", "first_frame_url": "first", "last_frame_url": "last"},
    )
    provider.estimate(req)
    provider.submit(req)
    assert seen["body"]["first_frame_url"].startswith("data:image/png;base64,")
    assert seen["body"]["last_frame_url"].startswith("data:image/gif;base64,")


def test_higgsfield_popcorn_resolves_local_image_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VINCI_ALLOW_LIVE_SPEND", "1")
    png = b"\x89PNG\r\n\x1a\n" + b"ref"
    provider = HiggsfieldProvider(
        api_key="key-id", api_secret="key-secret", cas=_mem_cas({"ref": png})
    )
    seen: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: int = 30) -> _FakeResp:
        seen["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResp({"request_id": "req-local-pop"})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    req = JobRequest(
        capability=Capability.T2I,
        model_id="higgsfield:popcorn-auto:2026-09",
        inputs={"prompt": "beats", "image_urls": ["ref"]},
    )
    provider.estimate(req)
    provider.submit(req)
    assert seen["body"]["image_urls"][0].startswith("data:image/png;base64,")


def test_fal_i2v_resolves_local_tail_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VINCI_ALLOW_LIVE_SPEND", "1")
    start = b"\x89PNG\r\n\x1a\n" + b"start"
    tail = b"\xff\xd8\xff" + b"tail"
    provider = FalProvider(api_key="fal-key", cas=_mem_cas({"start": start, "tail": tail}))
    seen: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: int = 30) -> _FakeResp:
        if request.get_method() == "POST":
            seen["body"] = json.loads(request.data.decode("utf-8"))
            return _FakeResp({"request_id": "req-tail"})
        return _FakeResp({"status": "IN_QUEUE"})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    req = JobRequest(
        capability=Capability.I2V,
        model_id="fal:seedance-1.5-pro-i2v:2026-09",
        inputs={"prompt": "walk", "image": "start", "tail_image_url": "tail"},
    )
    provider.estimate(req)
    provider.submit(req)
    assert seen["body"]["image_url"].startswith("data:image/png;base64,")
    assert seen["body"]["tail_image_url"].startswith("data:image/jpeg;base64,")


def test_google_veo_local_image_uses_inline_data(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VINCI_ALLOW_LIVE_SPEND", "1")
    png = b"\x89PNG\r\n\x1a\n" + b"still"
    provider = GoogleProvider(api_key="gem-key", cas=_mem_cas({"still": png}))
    seen: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: int = 30) -> _FakeResp:
        seen["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResp({"name": "models/veo-3.1-lite/operations/op-local"})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    req = JobRequest(
        capability=Capability.I2V,
        model_id="google:veo-3.1-lite:2026-08",
        inputs={"prompt": "turn", "image": "still"},
    )
    provider.estimate(req)
    ref = provider.submit(req)
    image = seen["body"]["instances"][0]["image"]
    assert ref.ref.endswith("/operations/op-local")
    assert image["inlineData"]["mimeType"] == "image/png"
    assert image["inlineData"]["data"] == base64.b64encode(png).decode("ascii")
    assert "bytesBase64Encoded" not in image


def test_higgsfield_t2v_submit_sends_aspect_and_duration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VINCI_ALLOW_LIVE_SPEND", "1")
    provider = HiggsfieldProvider(api_key="key-id", api_secret="key-secret")
    seen: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: int = 30) -> _FakeResp:
        seen["url"] = request.full_url
        seen["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResp({"request_id": "req-kling-t2v"})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    req = JobRequest(
        capability=Capability.T2V,
        model_id="higgsfield:kling-2.5-turbo-pro:2026-09",
        inputs={"prompt": "pan", "duration": "5", "aspect_ratio": "9:16"},
    )
    provider.estimate(req)
    ref = provider.submit(req)
    assert ref.ref == "req-kling-t2v"
    assert seen["body"]["prompt"] == "pan"
    assert seen["body"]["duration"] == "5"
    assert seen["body"]["aspect_ratio"] == "9:16"


def test_higgsfield_prompt_includes_optical_stack(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VINCI_ALLOW_LIVE_SPEND", "1")
    provider = HiggsfieldProvider(api_key="key-id", api_secret="key-secret")
    seen: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: int = 30) -> _FakeResp:
        seen["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResp({"request_id": "req-soul-optical"})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    req = JobRequest(
        capability=Capability.T2I,
        model_id="higgsfield:soul-standard:2026-09",
        inputs={
            "prompt": "oak cube",
            "camera": "handheld",
            "lens": "50mm",
            "look": "noir",
        },
    )
    provider.estimate(req)
    ref = provider.submit(req)
    assert ref.ref == "req-soul-optical"
    assert seen["body"]["prompt"] == "oak cube, shot on handheld, 50mm lens, noir look"


def test_magnific_kling_turbo_status_strips_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = MagnificProvider(api_key="mag-key")
    seen: dict[str, str] = {}

    def fake_urlopen(request: Any, timeout: int = 30) -> _FakeResp:
        seen["url"] = request.full_url
        return _FakeResp(
            {"data": {"status": "COMPLETED", "generated": ["https://cdn.example/k3.mp4"]}}
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    status = provider.status(
        ProviderJobRef(
            provider="magnific",
            ref="/v1/ai/image-to-video/kling-v3-turbo-1080p#task-k3",
        )
    )
    assert seen["url"].endswith("/v1/ai/image-to-video/kling-v3-turbo/task-k3")
    assert status.state == JobState.COMPLETED
    assert status.outputs == ["https://cdn.example/k3.mp4"]


def test_magnific_creative_upscaler_sends_public_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VINCI_ALLOW_LIVE_SPEND", "1")
    provider = MagnificProvider(api_key="mag-key")
    seen: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: int = 30) -> _FakeResp:
        seen["url"] = request.full_url
        seen["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResp({"data": {"task_id": "up-1"}})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    req = JobRequest(
        capability=Capability.I2I,
        model_id="magnific:upscaler-creative:2026-09",
        inputs={
            "prompt": "oak cube",
            "image": "https://cdn.example/still.png",
            "scale": "8x",
            "creativity": 3,
            "resemblance": -2,
            "hdr": 1,
            "fractality": 4,
            "optimized_for": "films_n_photography",
            "engine": "magnific_sharpy",
        },
    )
    provider.estimate(req)
    ref = provider.submit(req)
    assert ref.ref == "/v1/ai/image-upscaler#up-1"
    assert seen["url"].endswith("/v1/ai/image-upscaler")
    assert seen["body"]["image"] == "https://cdn.example/still.png"
    assert seen["body"]["scale_factor"] == "8x"
    assert seen["body"]["creativity"] == 3
    assert seen["body"]["resemblance"] == -2
    assert seen["body"]["hdr"] == 1
    assert seen["body"]["fractality"] == 4
    assert seen["body"]["optimized_for"] == "films_n_photography"
    assert seen["body"]["engine"] == "magnific_sharpy"


def test_magnific_precision_upscaler_skips_creative_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VINCI_ALLOW_LIVE_SPEND", "1")
    provider = MagnificProvider(api_key="mag-key")
    seen: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: int = 30) -> _FakeResp:
        seen["url"] = request.full_url
        seen["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResp({"data": {"task_id": "up-p"}})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    req = JobRequest(
        capability=Capability.I2I,
        model_id="magnific:upscaler-precision:2026-09",
        inputs={
            "prompt": "oak cube",
            "image": "https://cdn.example/still.png",
            "scale": "4x",
            "creativity": 9,
            "resemblance": 9,
            "optimized_for": "standard",
            "engine": "automatic",
        },
    )
    provider.estimate(req)
    provider.submit(req)
    assert seen["url"].endswith("/v1/ai/image-upscaler-precision")
    assert seen["body"]["scale_factor"] == "4x"
    assert "creativity" not in seen["body"]
    assert "resemblance" not in seen["body"]
    assert "optimized_for" not in seen["body"]
    assert "engine" not in seen["body"]


def test_google_generate_content_caches_data_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VINCI_ALLOW_LIVE_SPEND", "1")
    provider = GoogleProvider(api_key="gem-key")
    png = png_scene("gemini-inline")
    b64 = base64.b64encode(png).decode("ascii")
    seen: dict[str, str] = {}

    def fake_urlopen(request: Any, timeout: int = 30) -> _FakeResp:
        seen["url"] = request.full_url
        headers = {str(k).lower(): str(v) for k, v in request.header_items()}
        seen["key"] = headers.get("x-goog-api-key", "")
        return _FakeResp(
            {
                "responseId": "resp-1",
                "candidates": [
                    {
                        "content": {
                            "parts": [{"inlineData": {"mimeType": "image/png", "data": b64}}]
                        }
                    }
                ],
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    req = JobRequest(
        capability=Capability.T2I,
        model_id="google:gemini-flash-image:2026-08",
        inputs={"prompt": "still"},
    )
    provider.estimate(req)
    ref = provider.submit(req)
    assert seen["url"].endswith(":generateContent")
    assert seen["key"] == "gem-key"
    status = provider.status(ref)
    assert status.state == JobState.COMPLETED
    assert status.outputs[0].startswith("data:image/png;base64,")


def test_google_veo_status_live_completed(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = GoogleProvider(api_key="gem-key")
    seen: dict[str, str] = {}

    def fake_urlopen(request: Any, timeout: int = 30) -> _FakeResp:
        seen["url"] = request.full_url
        headers = {str(k).lower(): str(v) for k, v in request.header_items()}
        seen["key"] = headers.get("x-goog-api-key", "")
        return _FakeResp(
            {
                "name": "models/veo-3.1-lite/operations/op-9",
                "done": True,
                "response": {
                    "generateVideoResponse": {
                        "generatedSamples": [{"video": {"uri": "https://cdn.example/veo.mp4"}}]
                    }
                },
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    status = provider.status(
        ProviderJobRef(provider="google", ref="models/veo-3.1-lite/operations/op-9")
    )
    assert seen["url"].endswith("/v1beta/models/veo-3.1-lite/operations/op-9")
    assert seen["key"] == "gem-key"
    assert status.state == JobState.COMPLETED
    assert status.outputs == ["https://cdn.example/veo.mp4"]


def test_elevenlabs_submit_caches_mpeg_data_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VINCI_ALLOW_LIVE_SPEND", "1")
    provider = ElevenLabsProvider(api_key="el-key")
    audio = b"ID3\x04fake-mpeg"

    def fake_urlopen(request: Any, timeout: int = 30) -> _FakeResp:
        headers = {str(k).lower(): str(v) for k, v in request.header_items()}
        assert headers.get("xi-api-key") == "el-key"
        assert request.full_url.endswith("/v1/text-to-speech/default")
        return _FakeResp(audio)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    req = JobRequest(
        capability=Capability.TTS,
        model_id="elevenlabs:flash-v2.5:2026-08",
        inputs={"prompt": "hello"},
    )
    provider.estimate(req)
    ref = provider.submit(req)
    status = provider.status(ref)
    assert status.state == JobState.COMPLETED
    assert status.outputs[0].startswith("data:audio/mpeg;base64,")
    blob = base64.b64decode(status.outputs[0].split(",", 1)[1])
    assert blob.startswith(b"ID3")


def test_wait_status_retries_dns_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.error

    monkeypatch.setenv("VINCI_JOB_POLL_INTERVAL", "0")
    monkeypatch.setenv("VINCI_JOB_POLL_TIMEOUT", "2")
    engine = Engine(tmp_path)
    calls = {"n": 0}

    class _Provider:
        def status(self, ref: ProviderJobRef) -> JobStatus:
            del ref
            calls["n"] += 1
            if calls["n"] == 1:
                raise urllib.error.URLError(OSError(5, "No address associated with hostname"))
            return JobStatus(state=JobState.COMPLETED, outputs=["ok"])

    status = engine._wait_status(_Provider(), ProviderJobRef(provider="wavespeed", ref="x"))
    assert status.state == JobState.COMPLETED
    assert calls["n"] == 2


def test_wait_status_propagates_http_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import io
    import urllib.error
    from email.message import Message

    monkeypatch.setenv("VINCI_JOB_POLL_INTERVAL", "0")
    monkeypatch.setenv("VINCI_JOB_POLL_TIMEOUT", "2")
    engine = Engine(tmp_path)
    calls = {"n": 0}

    class _Provider:
        def status(self, ref: ProviderJobRef) -> JobStatus:
            del ref
            calls["n"] += 1
            raise urllib.error.HTTPError(
                "https://api.example/status",
                401,
                "Unauthorized",
                Message(),
                io.BytesIO(b"no"),
            )

    with pytest.raises(urllib.error.HTTPError):
        engine._wait_status(_Provider(), ProviderJobRef(provider="wavespeed", ref="x"))
    assert calls["n"] == 1


def test_ingest_data_uri_without_live_spend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    monkeypatch.delenv("VINCI_ALLOW_LIVE_SPEND", raising=False)
    engine = Engine(tmp_path)
    engine.init_home(demo=True)
    png = png_scene("data-uri-still")
    uri = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    status = JobStatus(state=JobState.COMPLETED, outputs=[uri])
    outputs = engine._ingest_status_outputs(
        status,
        kind=AssetKind.IMAGE,
        mime="image/png",
        secrets=[],
        run_id="run-data",
        model_id="google:gemini-flash-image:2026-08",
        prompt="still",
    )
    blob = engine.cas.get(outputs[0])
    assert blob == png
