"""screen-to-demo skill: deterministic ops, $0 mock path, engine e2e."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from vinci_media.ops import (
    EFFECT_KINDS,
    apply_effects,
    make_fixture_video,
    mock_transcribe,
    mux_audio,
    plan_effects,
    polish_script,
    probe,
    synth_voiceover,
)
from vinci_runtime.engine import Engine
from vinci_skills import SkillLoader

TRANSCRIPT = {
    "text": (
        "um so here is the dashboard. basically you can actually see every run."
        " like it updates live."
    ),
    "segments": [{"start": 0.0, "end": 6.0}],
    "duration": 6.0,
}


def test_polish_script_strips_fillers_and_times_lines() -> None:
    script = polish_script(TRANSCRIPT)
    assert "um" not in script["text"].split()
    assert "basically" not in script["text"].split()
    assert "actually" not in script["text"].split()
    assert "like" not in script["text"].split()
    assert len(script["lines"]) == 3
    starts = [line["start"] for line in script["lines"]]
    assert starts == sorted(starts)
    assert script["lines"][-1]["end"] == pytest.approx(6.0)


def test_plan_effects_covers_duration_without_overlap() -> None:
    plan = plan_effects(polish_script(TRANSCRIPT))
    effects = plan["effects"]
    assert len(effects) == 3
    for prev, nxt in zip(effects, effects[1:], strict=False):
        assert prev["end"] <= nxt["start"]
    assert effects[-1]["end"] == pytest.approx(6.0)
    assert plan["duration"] == pytest.approx(6.0)


def test_plan_effects_kinds_rotate_and_carry_params() -> None:
    plan = plan_effects(polish_script(TRANSCRIPT))
    kinds = [effect["type"] for effect in plan["effects"]]
    assert kinds == list(EFFECT_KINDS)
    assert plan["effects"][0]["params"]["scale"] > 1.0
    assert plan["effects"][1]["params"]["w"] > 0
    assert plan["effects"][2]["params"]["text"]


def test_apply_effects_preserves_duration(tmp_path: Path) -> None:
    src = make_fixture_video(tmp_path / "raw.mp4", duration=3.0)
    script = polish_script(mock_transcribe(src))
    plan = plan_effects(script)
    dest = tmp_path / "effected.mp4"
    apply_effects(src, dest, plan)
    info = probe(dest)
    assert info["duration"] == pytest.approx(3.0, abs=0.4)


def test_apply_effects_empty_plan_copies(tmp_path: Path) -> None:
    src = make_fixture_video(tmp_path / "raw.mp4", duration=2.0)
    dest = tmp_path / "plain.mp4"
    apply_effects(src, dest, {"effects": []})
    assert dest.exists()
    assert probe(dest)["duration"] == pytest.approx(2.0, abs=0.4)


def test_synth_voiceover_matches_script_duration(tmp_path: Path) -> None:
    script = polish_script(TRANSCRIPT)
    dest = tmp_path / "voice.wav"
    synth_voiceover(script, dest)
    info = probe(dest)
    assert info["duration"] == pytest.approx(6.0, abs=0.4)


def test_mux_audio_adds_audio_stream(tmp_path: Path) -> None:
    src = make_fixture_video(tmp_path / "raw.mp4", duration=3.0)
    script = polish_script(mock_transcribe(src))
    voice = tmp_path / "voice.wav"
    synth_voiceover(script, voice)
    dest = tmp_path / "muxed.mp4"
    mux_audio(src, voice, dest)
    info = probe(dest)
    assert info["duration"] == pytest.approx(3.0, abs=0.5)


def test_screen_to_demo_registered_and_free() -> None:
    loader = SkillLoader()
    skills = {s.id: s for s in loader.list_skills()}
    assert "@tryvinci/screen-to-demo" in skills
    inspect = loader.inspect("@tryvinci/screen-to-demo")
    assert inspect["est_cost"]["max"] == 0
    assert inspect["permissions"] == []


def test_screen_to_demo_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    engine = Engine(tmp_path)
    engine.init_home(demo=True)
    # Non-3s duration catches mock_transcribe falling back to its 3.0s default
    # (engine-materialized CAS blobs carry no extension - regression guard).
    media = make_fixture_video(tmp_path / "recording.mp4", duration=5.0)
    run = engine.start_run("@tryvinci/screen-to-demo", {"media": str(media)})
    assert run["state"] == "completed", json.dumps(run, default=str)[:800]
    assert run["estimate"]["total"] == 0
    assert len(run["job_ids"]) == 7
    assert run["outputs"]
    asset = engine.store.get_asset(run["outputs"][-1])
    assert asset is not None
    assert asset.kind.value == "video"
    out = engine._materialize(asset.uri)
    assert probe(out)["duration"] > 4.0
    receipt = engine.store.get_job(run["job_ids"][-1])
    assert receipt is not None and receipt.receipt is not None
    assert receipt.receipt.computed_cost == 0

def test_transcribe_media_uses_whisper_when_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    media = make_fixture_video(tmp_path / "recording.mp4", duration=2.0)
    payload = tmp_path / "payload.json"
    payload.write_text(json.dumps({
        "transcription": [
            {"offsets": {"from": 0, "to": 1500}, "text": " Hello world"},
            {"offsets": {"from": 1500, "to": 2000}, "text": " again"},
        ]
    }))
    fake_whisper = tmp_path / "whisper-cli"
    fake_whisper.write_text(
        "#!/bin/sh\n"
        "while [ $# -gt 0 ]; do\n"
        "  if [ \"$1\" = \"-of\" ]; then shift; OUT=\"$1\"; fi\n"
        "  shift\n"
        "done\n"
        f"cp {payload} \"${{OUT}}.json\"\n"
    )
    fake_whisper.chmod(0o755)
    fake_model = tmp_path / "ggml-tiny.bin"
    fake_model.write_bytes(b"fake")
    monkeypatch.setenv("VINCI_WHISPER", str(fake_whisper))
    monkeypatch.setenv("VINCI_WHISPER_MODEL", str(fake_model))
    from vinci_media.ops import transcribe_media
    result = transcribe_media(media)
    assert result["engine"] == "whisper.cpp"
    assert result["text"] == "Hello world again"
    assert result["words"][0]["end"] == 1.5
    assert result["duration"] == 2.0


def test_transcribe_media_falls_back_to_mock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    media = make_fixture_video(tmp_path / "recording.mp4", duration=2.0)
    monkeypatch.setenv("VINCI_WHISPER", str(tmp_path / "missing"))
    monkeypatch.setenv("VINCI_WHISPER_MODEL", str(tmp_path / "missing.bin"))
    from vinci_media.ops import transcribe_media
    result = transcribe_media(media)
    assert result["engine"] == "mock"


def test_tts_voiceover_uses_piper_when_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from vinci_media.ops import tts_voiceover
    # pre-make a real wav the fake piper "synthesizes"
    clip = tmp_path / "clip.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=520:duration=0.5", str(clip)],
        check=True, capture_output=True,
    )
    fake_piper = tmp_path / "piper"
    fake_piper.write_text(
        "#!/bin/sh\n"
        "while [ $# -gt 0 ]; do\n"
        "  if [ \"$1\" = \"-f\" ]; then shift; OUT=\"$1\"; fi\n"
        "  shift\n"
        "done\n"
        f"cp {clip} \"$OUT\"\n"
    )
    fake_piper.chmod(0o755)
    fake_model = tmp_path / "voice.onnx"
    fake_model.write_bytes(b"fake")
    monkeypatch.setenv("VINCI_PIPER", str(fake_piper))
    monkeypatch.setenv("VINCI_PIPER_MODEL", str(fake_model))
    script = {
        "lines": [
            {"line": "first line", "start": 0.0, "end": 0.5},
            {"line": "second line", "start": 1.0, "end": 1.5},
        ],
        "duration": 2.0,
    }
    from vinci_media.ops import probe as media_probe
    out = tts_voiceover(script, tmp_path / "vo.wav")
    assert out.is_file()
    assert abs(media_probe(out)["duration"] - 2.0) < 0.1


def test_tts_voiceover_falls_back_to_tones(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from vinci_media.ops import synth_voiceover, tts_voiceover
    monkeypatch.setenv("VINCI_PIPER", str(tmp_path / "missing"))
    monkeypatch.setenv("VINCI_PIPER_MODEL", str(tmp_path / "missing.onnx"))
    script = {
        "lines": [{"line": "hello there", "start": 0.0, "end": 1.0}],
        "duration": 1.5,
    }
    via_fallback = tts_voiceover(script, tmp_path / "a.wav")
    direct = synth_voiceover(script, tmp_path / "b.wav")
    assert via_fallback.read_bytes() == direct.read_bytes()

