from __future__ import annotations

from pathlib import Path

import pytest
from vinci_media.ops import make_fixture_video, mock_transcribe, select_windows
from vinci_protocol.enums import Capability
from vinci_protocol.models import JobRequest
from vinci_provider_elevenlabs import ElevenLabsProvider
from vinci_provider_sdk.catalog_provider import LiveSpendDisabled
from vinci_runtime.engine import Engine
from vinci_skills import SkillLoader


def test_phase2_skills_present() -> None:
    ids = {s.id for s in SkillLoader().list_skills()}
    for name in (
        "@tryvinci/talking-photo",
        "@tryvinci/lipsync",
        "@tryvinci/emote-animate",
        "@tryvinci/video-upscale",
        "@tryvinci/image-upscale",
        "@tryvinci/tts",
        "@tryvinci/voice-clone",
        "@tryvinci/podcast-to-shorts",
        "@tryvinci/clip-select",
        "@tryvinci/reframe-9x16",
        "@tryvinci/captions-burn",
        "@tryvinci/streamer-split",
        "@tryvinci/cinema-sequence",
        "@tryvinci/first-last-frame",
        "@tryvinci/soul-character",
    ):
        assert name in ids


def test_elevenlabs_refuses_live_spend() -> None:
    req = JobRequest(capability=Capability.TTS, inputs={"prompt": "hello"})
    live = ElevenLabsProvider(api_key="sk-never-spend")
    live.estimate(req)
    with pytest.raises(LiveSpendDisabled):
        live.submit(req)


def test_clean_room_transcript_mentions_pricing(tmp_path: Path) -> None:
    clip = make_fixture_video(tmp_path / "pod.mp4", duration=3.0)
    transcript = mock_transcribe(clip)
    windows = select_windows(transcript, query="pricing", count=1)
    assert windows
    assert windows[0]["end"] > windows[0]["start"]


def test_generate_skills_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    engine = Engine(tmp_path)
    engine.init_home(demo=True)
    tts = engine.start_run("@tryvinci/tts", {"prompt": "hello from the bench"})
    assert tts["state"] == "completed"
    assert tts["estimate"]["total"] == 0
    talk = engine.start_run("@tryvinci/talking-photo", {"prompt": "say hello"})
    assert talk["state"] == "completed"
    hits = engine.find("hello")
    assert hits


def test_podcast_to_shorts_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    engine = Engine(tmp_path)
    engine.init_home(demo=True)
    media = make_fixture_video(tmp_path / "podcast.mp4", duration=3.0)
    run = engine.start_run(
        "@tryvinci/podcast-to-shorts",
        {"media": str(media), "query": "pricing"},
    )
    assert run["state"] == "completed"
    assert run["estimate"]["total"] == 0
    assert len(run["job_ids"]) == 5
    assert run["outputs"]
    asset = engine.store.get_asset(run["outputs"][0])
    assert asset is not None
    assert asset.kind.value == "video"
    receipt = engine.store.get_job(run["job_ids"][-1])
    assert receipt is not None
    assert receipt.receipt is not None
    assert receipt.receipt.computed_cost == 0
    hits = engine.find("pricing")
    assert any("pricing" in (h.get("transcript") or "").lower() or h["score"] > 0 for h in hits)


def test_streamer_split_and_reframe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    engine = Engine(tmp_path)
    engine.init_home(demo=True)
    media = make_fixture_video(tmp_path / "long.mp4", duration=3.0)
    split = engine.start_run("@tryvinci/streamer-split", {"media": str(media), "count": 3})
    assert split["state"] == "completed"
    assert len(split["outputs"]) == 3
    reframed = engine.start_run("@tryvinci/reframe-9x16", {"media": str(media)})
    assert reframed["state"] == "completed"


def test_remaining_first_party_skills_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    monkeypatch.delenv("VINCI_ALLOW_LIVE_SPEND", raising=False)
    engine = Engine(tmp_path)
    engine.init_home(demo=True)
    media = make_fixture_video(tmp_path / "src.mp4", duration=2.0)
    path = str(media)
    cases = (
        ("@tryvinci/lipsync", {"prompt": "sync", "audio": path, "video": path}, 1),
        ("@tryvinci/emote-animate", {"prompt": "smile", "image": path}, 1),
        ("@tryvinci/video-upscale", {"prompt": "up", "media": path}, 1),
        ("@tryvinci/voice-clone", {"prompt": "hello clone", "reference": path}, 1),
        ("@tryvinci/captions-burn", {"media": path, "text": "pricing"}, 1),
        ("@tryvinci/clip-select", {"media": path, "query": "pricing"}, 3),
    )
    for skill, inputs, jobs in cases:
        run = engine.start_run(skill, inputs)
        assert run["state"] == "completed", skill
        assert (run.get("estimate") or {}).get("total") == 0, skill
        assert len(run.get("job_ids") or []) == jobs, skill
        assert run.get("outputs"), skill


def test_image_upscale_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    monkeypatch.delenv("VINCI_ALLOW_LIVE_SPEND", raising=False)
    engine = Engine(tmp_path)
    engine.init_home(demo=True)
    src = engine.start_run("@tryvinci/image-generate", {"prompt": "still for upscale"})
    assert src["state"] == "completed"
    digest = src["outputs"][0]
    up = engine.start_run(
        "@tryvinci/image-upscale",
        {"prompt": "upscale", "media": digest},
        model_id="mock:png:v1",
    )
    assert up["state"] == "completed"
    assert up["estimate"]["total"] == 0
    assert up["outputs"]
    receipt = engine.store.get_receipt(up["job_ids"][0])
    assert receipt is not None
    assert receipt.computed_cost == 0


def test_soul_character_workflow_is_zero_on_mock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    engine = Engine(tmp_path)
    engine.init_home(demo=True)
    run = engine.start_run(
        "@tryvinci/soul-character",
        {"prompt": "oak cube character sheet", "lighting": "studio"},
    )
    assert run["state"] == "completed"
    assert run["estimate"]["total"] == 0
    assert len(run["job_ids"]) == 2
    assert run["nodes"]["sheet"]["output"]
    assert run["nodes"]["lock"]["output"]
    assert run["nodes"]["sheet"]["output"] != run["nodes"]["lock"]["output"]
    assert run["nodes"]["lock"]["output"] == run["outputs"][0]
