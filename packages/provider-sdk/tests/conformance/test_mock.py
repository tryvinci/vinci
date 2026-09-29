from __future__ import annotations

import logging
import struct
from pathlib import Path

from vinci_core.redact import redact_mapping
from vinci_protocol.enums import Capability
from vinci_protocol.models import Job, JobRequest, JobState, Receipt
from vinci_provider_sdk.conformance import run_conformance
from vinci_provider_sdk.mock import (
    MP4_SWATCH,
    PNG_SWATCH,
    MockProvider,
    mock_dimensions,
    mp4_dimensions,
    mp4_duration_seconds,
    mp4_scene,
    png_scene,
)
from vinci_provider_sdk.shot import compose_shot_prompt
from vinci_storage.cas import ContentAddressedStore
from vinci_storage.sqlite_store import SqliteStore

SECRET = "sk-conformance-never-log-me"


def test_mock_png_swatch_is_visible() -> None:
    assert PNG_SWATCH.startswith(b"\x89PNG\r\n\x1a\n")
    width, height = struct.unpack(">II", PNG_SWATCH[16:24])
    assert width == 960
    assert height == 540
    other = png_scene("a different prompt")
    assert other != PNG_SWATCH
    assert png_scene("mock") == PNG_SWATCH


def test_mock_png_honors_aspect_ratio() -> None:
    assert mock_dimensions(None) == (960, 540)
    assert mock_dimensions("") == (960, 540)
    assert mock_dimensions("16:9") == (960, 540)
    assert mock_dimensions("9:16") == (540, 960)
    assert mock_dimensions("1:1") == (720, 720)
    portrait = png_scene("portrait oak cube", 540, 960)
    width, height = struct.unpack(">II", portrait[16:24])
    assert (width, height) == (540, 960)
    assert portrait != png_scene("portrait oak cube")


def test_mock_mp4_honors_aspect_ratio() -> None:
    portrait = mp4_scene("portrait oak cube tumbling", 540, 960)
    assert portrait[4:8] == b"ftyp"
    assert mp4_dimensions(portrait) == (540, 960)


def test_compose_shot_prompt_skips_empty_optical() -> None:
    assert compose_shot_prompt({"prompt": "oak"}) == "oak"
    assert compose_shot_prompt({"prompt": "oak", "camera": "", "lens": "", "look": ""}) == "oak"
    assert (
        compose_shot_prompt(
            {"prompt": "oak", "camera": "handheld", "lens": "50mm", "look": "noir"}
        )
        == "oak, shot on handheld, 50mm lens, noir look"
    )
    assert compose_shot_prompt({"prompt": "oak", "motion": "static"}) == "oak"
    assert compose_shot_prompt({"prompt": "oak", "motion": "orbit"}) == "oak, orbit camera move"
    assert (
        compose_shot_prompt(
            {
                "prompt": "oak",
                "aperture": "f/1.4",
                "genre": "drama",
                "scene": "podcast",
            }
        )
        == "oak, f/1.4 aperture, drama genre, podcast talking scene"
    )
    assert compose_shot_prompt({"prompt": "oak", "scene": "general"}) == "oak"
    assert (
        compose_shot_prompt(
            {"prompt": "oak", "lighting": "available", "palette": "filmic"}
        )
        == "oak"
    )
    assert (
        compose_shot_prompt({"prompt": "oak", "lighting": "neon", "palette": "teal-orange"})
        == "oak, neon lighting, teal-orange palette"
    )


def test_mock_dimensions_ultrawide() -> None:
    assert mock_dimensions("21:9") == (960, 412)


def test_mock_mp4_honors_duration() -> None:
    short = mp4_scene("duration oak", duration=1.0)
    long = mp4_scene("duration oak", duration=3.0)
    assert short[4:8] == b"ftyp"
    assert long[4:8] == b"ftyp"
    assert short != long
    seconds = mp4_duration_seconds(long)
    assert seconds is not None and 2.5 <= seconds <= 3.5


def test_mock_png_honors_optical_stack(tmp_path: Path) -> None:
    cas = ContentAddressedStore(tmp_path / "cas")
    provider = MockProvider(cas, api_key=SECRET)
    plain = JobRequest(capability=Capability.T2I, model_id="mock:png:v1", inputs={"prompt": "oak"})
    optic = JobRequest(
        capability=Capability.T2I,
        model_id="mock:png:v1",
        inputs={"prompt": "oak", "camera": "handheld", "lens": "50mm", "look": "noir"},
    )
    provider.estimate(plain)
    provider.estimate(optic)
    plain_digest = provider.status(provider.submit(plain)).outputs[0]
    optic_digest = provider.status(provider.submit(optic)).outputs[0]
    assert plain_digest != optic_digest


def test_mock_mp4_swatch_is_playable() -> None:
    assert MP4_SWATCH[4:8] == b"ftyp"
    assert len(MP4_SWATCH) > 1000
    assert mp4_dimensions(MP4_SWATCH) == (960, 540)
    assert mp4_scene("mock") == MP4_SWATCH
    other = mp4_scene("a different prompt")
    assert other[4:8] == b"ftyp"
    assert other != MP4_SWATCH
    assert mp4_dimensions(other) == (960, 540)


def test_mock_conformance(tmp_path: Path) -> None:
    cas = ContentAddressedStore(tmp_path / "cas")
    provider = MockProvider(cas, api_key=SECRET)
    run_conformance(provider, secret=SECRET)


def test_cas_replay_is_zero(tmp_path: Path) -> None:
    cas = ContentAddressedStore(tmp_path / "cas")
    provider = MockProvider(cas, api_key=SECRET)
    req = JobRequest(capability=Capability.T2I, inputs={"prompt": "same"})
    first = provider.estimate(req)
    assert first.cached is False
    provider.submit(req)
    second = provider.estimate(req)
    assert second.cached is True
    assert second.amount == 0.0


def test_mock_provider_png_uses_aspect(tmp_path: Path) -> None:
    cas = ContentAddressedStore(tmp_path / "cas")
    provider = MockProvider(cas, api_key=SECRET)
    req = JobRequest(
        capability=Capability.T2I,
        model_id="mock:png:v1",
        inputs={"prompt": "portrait oak", "aspect_ratio": "9:16"},
    )
    provider.estimate(req)
    ref = provider.submit(req)
    digest = provider.status(ref).outputs[0]
    blob = cas.get(digest)
    width, height = struct.unpack(">II", blob[16:24])
    assert (width, height) == (540, 960)


def test_secrets_never_hit_jobs_receipts_or_logs(tmp_path: Path, caplog) -> None:  # type: ignore[no-untyped-def]
    cas = ContentAddressedStore(tmp_path / "cas")
    store = SqliteStore(tmp_path / "vinci.sqlite")
    provider = MockProvider(cas, api_key=SECRET)
    caplog.set_level(logging.DEBUG)
    req = JobRequest(
        capability=Capability.T2I,
        inputs={"prompt": "hi", "callback_token": SECRET},
        model_id="mock:png:v1",
    )
    estimate = provider.estimate(req)
    ref = provider.submit(req)
    status = provider.status(ref)
    job = Job(
        id="job_secret",
        model_id="mock:png:v1",
        state=JobState.COMPLETED,
        inputs=req.inputs,
        outputs=status.outputs,
        estimate=estimate,
        provider_job_ref=ref.ref,
        idempotency_key="k1",
    )
    store.put_job(job, secret_values=[SECRET])
    receipt = Receipt(
        job_id="job_secret",
        model_id="mock:png:v1",
        provider="mock",
        list_price=0.0,
        unit_count=1,
        computed_cost=0.0,
        currency="USD",
        pricing_snapshot_at=estimate.pricing_snapshot_at,
        cached=False,
    )
    store.put_receipt(receipt, secret_values=[SECRET])
    loaded = store.get_job("job_secret")
    assert loaded is not None
    dumped = loaded.model_dump()
    assert SECRET not in str(dumped)
    assert SECRET not in str(store.get_receipt("job_secret"))
    assert SECRET not in caplog.text
    mcp_payload = redact_mapping(
        {"tool": "vinci.image_generate", "inputs": req.inputs},
        extra_values=[SECRET],
    )
    assert SECRET not in str(mcp_payload)
