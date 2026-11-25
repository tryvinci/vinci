"""Music and SFX models (COREPRODUC-551): catalog rows, the mock WAVs, and the ElevenLabs calls."""

from __future__ import annotations

import io
import json
import wave
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from vinci_core.catalog import load_bundled_catalog
from vinci_protocol.enums import Capability
from vinci_protocol.models import JobRequest


def test_catalog_rows_price_one_generation() -> None:
    eleven = load_bundled_catalog("elevenlabs")
    sfx = eleven.by_id("elevenlabs:sound-effects-v2:2026-11")
    music = eleven.by_id("elevenlabs:music-v1:2026-11")
    # elevenlabs.io/pricing/api, 2026-11-09: $0.12 and $0.15 a minute; a job is priced by its length.
    assert (sfx.capabilities, sfx.pricing.amount, sfx.constraints.max_duration) == (
        [Capability.SFX],
        0.06,
        30,
    )
    assert (music.capabilities, music.pricing.amount, music.pricing.unit) == (
        [Capability.MUSIC],
        0.15,
        "minute",
    )
    assert eleven.endpoint_for(sfx.id) == "eleven_text_to_sound_v2"
    assert eleven.endpoint_for(music.id) == "music_v1"
    mock_ids = {m.id: m.capabilities for m in load_bundled_catalog("mock").models}
    assert mock_ids["mock:music:v1"] == [Capability.MUSIC] and mock_ids["mock:sfx:v1"] == [
        Capability.SFX
    ]


def test_mock_cues_are_real_wav_files_of_the_asked_length() -> None:
    from vinci_provider_sdk.mock import wav_cue

    for kind in ("music", "sfx"):
        with wave.open(io.BytesIO(wav_cue(kind, "a door creaks", 2.5))) as wav:
            assert wav.getnframes() / wav.getframerate() == 2.5, kind
    assert wav_cue("music", "a", 1) != wav_cue("music", "b", 1)  # each cue sounds different


class _Reply:
    def read(self) -> bytes:
        return b"ID3\x04\x00fake-mp3"

    def __enter__(self) -> _Reply:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_elevenlabs_sound_effects_and_music_requests() -> None:
    from vinci_provider_elevenlabs.plugin import ElevenLabsProvider

    provider = ElevenLabsProvider(api_key="eleven-test-key")
    sent: list[Any] = []

    def fake_urlopen(request: Any, timeout: int = 0) -> _Reply:
        sent.append(request)
        return _Reply()

    jobs = [
        (
            Capability.SFX,
            "elevenlabs:sound-effects-v2:2026-11",
            {"prompt": "Door creaks", "duration": 45},
        ),
        (Capability.MUSIC, "elevenlabs:music-v1:2026-11", {"prompt": "Slow piano", "duration": 20}),
    ]
    with (
        mock.patch("vinci_provider_sdk.catalog_provider.allow_live_spend", return_value=True),
        mock.patch("urllib.request.urlopen", side_effect=fake_urlopen),
    ):
        for capability, model_id, inputs in jobs:
            req = JobRequest(capability=capability, model_id=model_id, inputs=inputs)
            provider.estimate(req)
            status = provider.status(provider.submit(req))
            assert status.outputs[0].startswith("data:audio/mpeg;base64,")
    sfx, music = sent
    assert sfx.full_url == "https://api.elevenlabs.io/v1/sound-generation"
    assert json.loads(sfx.data) == {
        "text": "Door creaks",
        "model_id": "eleven_text_to_sound_v2",
        "duration_seconds": 30.0,
    }
    assert music.full_url == "https://api.elevenlabs.io/v1/music"
    assert json.loads(music.data) == {
        "prompt": "Slow piano",
        "model_id": "music_v1",
        "force_instrumental": True,
        "music_length_ms": 20000,
    }
    assert sfx.get_header("Xi-api-key") == "eleven-test-key"


def test_elevenlabs_voices_and_no_default_voice(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Voice field's list, and no voice "default": it failed after the price check (live test
    of 2026-11-09)."""
    from vinci_provider_elevenlabs.plugin import ElevenLabsProvider

    provider = ElevenLabsProvider(api_key="eleven-test-key")
    voices = [{"voice_id": "EXAVITQu4vr4xnSDxMaL", "name": "Sarah", "category": "premade"}]
    with mock.patch.object(provider, "_get_json", return_value={"voices": [*voices, {}]}) as get:
        assert provider.voices() == [
            {"id": "EXAVITQu4vr4xnSDxMaL", "name": "Sarah", "category": "premade"}
        ]
    assert get.call_args.args[0] == "https://api.elevenlabs.io/v1/voices"
    monkeypatch.delenv("ELEVENLABS_VOICE_ID", raising=False)
    req = JobRequest(
        capability=Capability.TTS,
        model_id="elevenlabs:flash-v2.5:2026-08",
        inputs={"prompt": "You kept the key?"},
    )
    with mock.patch("vinci_provider_sdk.catalog_provider.allow_live_spend", return_value=True):
        provider.estimate(req)
        with pytest.raises(ValueError, match="no ElevenLabs voice"):
            provider.submit(req)


def test_a_removed_voice_names_the_character_and_asks_for_another_voice(tmp_path: Path) -> None:
    """COREPRODUC-797 (found before the first report): ElevenLabs Default voices expire on
    2026-12-31. A fake ElevenLabs answers the documented 404 ``voice_not_found``: the plugin says
    which voice, and the engine names the Lamp Oil character who speaks in it. Other errors keep
    their body, so the runtime can still show a 403 reason."""
    import shutil
    import urllib.error

    from vinci_olf.api import lamp_oil_path
    from vinci_olf.project import load
    from vinci_olf.render import VOICE_CODES, voice_refused
    from vinci_olf.resolve import resolve
    from vinci_provider_elevenlabs.plugin import VOICE_REFUSED, ElevenLabsProvider

    def refusal(code: int, body: dict[str, Any]) -> urllib.error.HTTPError:
        data = io.BytesIO(json.dumps(body).encode())
        return urllib.error.HTTPError("https://api.elevenlabs.io", code, "x", {}, data)  # type: ignore[arg-type]

    gone = {"detail": {"type": "not_found", "code": "voice_not_found", "status": "voice_not_found"}}
    req = JobRequest(
        capability=Capability.TTS,
        model_id="elevenlabs:flash-v2.5:2026-08",
        inputs={"prompt": "Tell me.", "voice_id": "pFZP5JQG7iQjIQuC4Bku"},
    )
    provider = ElevenLabsProvider(api_key="eleven-test-key")
    with mock.patch("vinci_provider_sdk.catalog_provider.allow_live_spend", return_value=True):
        provider.estimate(req)
        with mock.patch.object(provider, "_post_bytes", side_effect=refusal(404, gone)):
            with pytest.raises(ValueError) as refused:
                provider.submit(req)
        with mock.patch.object(provider, "_post_bytes", side_effect=refusal(500, {"detail": "x"})):
            with pytest.raises(urllib.error.HTTPError) as down:
                provider.submit(req)
    assert str(refused.value) == (
        "ElevenLabs cannot speak in voice pFZP5JQG7iQjIQuC4Bku (voice_not_found): pick another voice"
    )
    assert down.value.code == 500 and json.loads(down.value.read()) == {"detail": "x"}
    sample = lamp_oil_path()
    assert sample is not None
    media = json.loads((sample / "media.json").read_text())  # the media are shared links
    root = Path(shutil.copytree(sample, tmp_path / "show"))
    for rel in media:  # a stand-in, as on the host
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(b"")
    show = load(root, hashes={rel: item["sha256"] for rel, item in media.items()})
    job = {"view": resolve(show, "e01/s03/sh010")}
    assert voice_refused(job, str(refused.value)) == (
        'Mira\'s voice "Lily - Velvety Actress" (pFZP5JQG7iQjIQuC4Bku) is gone from ElevenLabs '
        "or not on this account (voice_not_found). Pick another voice for Mira"
    )
    assert (
        voice_refused(job, "HTTP Error 500") == voice_refused(job, "voice_not_found: v_other") == ""
    )
    # One voice for two speakers names both (PR-Agent on #807); olf keeps the plugin's codes.
    lily = job["view"]["characters"][0]["voice"]
    job["view"]["characters"] = [{"name": "Mira", "voice": lily}, {"name": "Tomas", "voice": lily}]
    assert voice_refused(job, str(refused.value)).startswith("Mira and Tomas's voice")
    assert VOICE_CODES == VOICE_REFUSED


class _Answer:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def read(self, *args: object) -> bytes:
        return self.body

    def __enter__(self) -> _Answer:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_elevenlabs_instant_voice_clone_and_clone_job(monkeypatch: pytest.MonkeyPatch) -> None:
    """COREPRODUC-559: a real clone call (POST /v1/voices/add, multipart name and files). A
    voice_clone job clones the reference, speaks the prompt, and deletes the clone."""
    import base64

    from vinci_provider_elevenlabs.plugin import ElevenLabsProvider

    provider = ElevenLabsProvider(api_key="eleven-test-key")
    calls: list[Any] = []

    def fake_urlopen(request: Any, timeout: int = 0) -> _Answer:
        calls.append(request)
        if request.full_url.endswith("/v1/voices/add"):
            return _Answer(b'{"voice_id": "clone_123", "requires_verification": false}')
        return _Answer(b"ID3\x04\x00speech" if "text-to-speech" in request.full_url else b"")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    sample = b"ID3\x04\x00recording"
    assert provider.clone_voice('Mira "Sol"\r\n', [("take.mp3", sample)]) == "clone_123"
    add = calls[0]
    assert (add.get_method(), add.get_header("Xi-api-key")) == ("POST", "eleven-test-key")
    assert add.get_header("Content-type").startswith("multipart/form-data; boundary=")
    assert b'name="name"\r\n\r\nMira Sol\r\n' in add.data  # no quote or line break in a header
    assert b'name="files"; filename="take.mp3"\r\nContent-Type: audio/mpeg' in add.data
    assert sample in add.data
    calls.clear()
    reference = "data:audio/mpeg;base64," + base64.b64encode(sample).decode()
    req = JobRequest(
        capability=Capability.VOICE_CLONE,
        model_id="elevenlabs:voice-clone:2026-08",
        inputs={"prompt": "You kept the key?", "reference": reference},
    )
    with mock.patch("vinci_provider_sdk.catalog_provider.allow_live_spend", return_value=True):
        provider.estimate(req)
        status = provider.status(provider.submit(req))
    assert status.outputs[0].startswith("data:audio/mpeg;base64,")
    assert [(c.get_method(), c.full_url.rsplit("/v1/", 1)[1]) for c in calls] == [
        ("POST", "voices/add"),
        ("POST", "text-to-speech/clone_123"),
        ("DELETE", "voices/clone_123"),  # a job does not keep a voice slot
    ]
    no_reference = JobRequest(
        capability=Capability.VOICE_CLONE,
        model_id="elevenlabs:voice-clone:2026-08",
        inputs={"prompt": "Hello"},
    )
    with mock.patch("vinci_provider_sdk.catalog_provider.allow_live_spend", return_value=True):
        provider.estimate(no_reference)
        with pytest.raises(ValueError, match="needs reference audio"):
            provider.submit(no_reference)


def test_clone_reference_over_the_limit_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """A clone reference larger than MAX_REFERENCE, downloaded or a data: URI, is refused, not
    cut short and sent (review of #528)."""
    import base64

    from vinci_provider_elevenlabs import plugin

    url = {"reference": "https://example.com/take.mp3"}
    big = b"ID3" + b"\x00" * 20
    monkeypatch.setattr(plugin, "MAX_REFERENCE", 8)
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _Answer(big))
    with pytest.raises(ValueError, match="reference audio is larger than"):
        plugin._reference_audio(url)
    with pytest.raises(ValueError, match="reference audio is larger than"):
        plugin._reference_audio(
            {"reference": "data:audio/mpeg;base64," + base64.b64encode(big).decode()}
        )
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _Answer(b"ID3\x00\x00"))
    assert plugin._reference_audio(url) == ("reference.mp3", b"ID3\x00\x00")
