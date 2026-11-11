from __future__ import annotations

import base64
import logging
import mimetypes
import os
import re
import urllib.request
import uuid

from vinci_protocol.enums import Capability, JobState
from vinci_protocol.models import (
    JobRequest,
    JobStatus,
    ModelSpec,
    ProviderAuth,
    ProviderJobRef,
    ProviderManifest,
)
from vinci_provider_sdk.catalog_provider import CatalogBackedProvider

# https://elevenlabs.io/docs/api-reference (2026-11-09). Both answer with raw audio (mp3).
SFX_URL = "https://api.elevenlabs.io/v1/sound-generation"  # text, duration_seconds 0.5 to 30
VOICES_URL = "https://api.elevenlabs.io/v1/voices"  # the voices a line can be spoken in
VOICES_ADD_URL = "https://api.elevenlabs.io/v1/voices/add"  # Instant Voice Cloning: name, files
CLONE_TTS_MODEL = "eleven_multilingual_v2"  # speaks a fresh clone (the clone row has no TTS model)
MAX_REFERENCE = 25 * 1024 * 1024  # a downloaded clone reference; a larger file is refused, not cut
log = logging.getLogger("vinci.provider")


def _multipart(fields: dict[str, str], files: list[tuple[str, bytes]]) -> tuple[bytes, str]:
    """A multipart/form-data body: the text fields, then each file as a ``files`` part."""
    boundary = uuid.uuid4().hex
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        for k, v in fields.items()
    ]
    for name, data in files:
        mime = mimetypes.guess_type(name)[0] or "audio/mpeg"
        head = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{name}"\r\n'
        )
        parts.append(f"{head}Content-Type: {mime}\r\n\r\n".encode() + data + b"\r\n")
    body = b"".join([*parts, f"--{boundary}--\r\n".encode()])
    return body, f"multipart/form-data; boundary={boundary}"


def _reference_audio(inputs: dict[str, object]) -> tuple[str, bytes]:
    """A clone job's reference audio, from a ``data:`` URI or an https URL: (file name, bytes)."""
    for key in ("reference", "audio", "audio_url"):
        value = str(inputs.get(key) or "")
        if value.startswith("data:") and "," in value:
            data = base64.b64decode(value.split(",", 1)[1])
        elif value.startswith("https://"):
            with urllib.request.urlopen(value, timeout=60) as response:  # noqa: S310 - https only
                data = response.read(MAX_REFERENCE + 1)
        else:
            continue
        if len(data) > MAX_REFERENCE:  # from either source: refused, not cut and sent
            raise ValueError(f"the reference audio is larger than {MAX_REFERENCE >> 20} MB")
        return ("reference.wav" if data[:4] == b"RIFF" else "reference.mp3"), data
    raise ValueError("a voice clone needs reference audio: a data: URI or an https URL")


MUSIC_URL = "https://api.elevenlabs.io/v1/music"  # prompt, music_length_ms 3000 to 600000


class ElevenLabsProvider(CatalogBackedProvider):
    catalog_name = "elevenlabs"
    provider_id = "elevenlabs"
    secret_name = "ELEVENLABS_API_KEY"
    manifest = ProviderManifest(
        id="elevenlabs",
        display_name="ElevenLabs",
        auth=ProviderAuth(env_vars=["ELEVENLABS_API_KEY"]),
        docs_url="https://elevenlabs.io/app/settings/api-keys",
    )

    def voices(self) -> list[dict[str, str]]:
        """The account's voices (``GET /v1/voices``, no charge): ``[{"id", "name", "category"}]``.

        Raises:
            PermissionError: No API key.
        """
        if not self._api_key:
            raise PermissionError("missing ELEVENLABS_API_KEY")
        body = self._get_json(VOICES_URL, {"xi-api-key": str(self._api_key)})
        rows = [v for v in body.get("voices") or [] if isinstance(v, dict) and v.get("voice_id")]
        return [
            {
                "id": str(v["voice_id"]),
                "name": str(v.get("name") or v["voice_id"]),
                "category": str(v.get("category") or ""),
            }
            for v in rows
        ]

    def clone_voice(
        self, name: str, samples: list[tuple[str, bytes]], description: str = ""
    ) -> str:
        """Make an Instant Voice Clone (``POST /v1/voices/add``) and return its ``voice_id``.

        The caller makes sure the person has the right to the voice and the speaker's consent
        (the Studio asks). ElevenLabs wants at least 10 s of clean speech (1 to 2 minutes is
        best); the clone takes one of the account's voice slots.

        Raises:
            PermissionError: No API key.
            RuntimeError: ElevenLabs gave no voice ID.
        """
        if not self._api_key:
            raise PermissionError("missing ELEVENLABS_API_KEY")

        def clean(text: str) -> str:  # a quote or a line break would end a multipart header
            return re.sub(r'["\r\n]', "", text).strip()[:100]

        fields = {"name": clean(name) or "Vinci voice"}
        fields |= {"description": clean(description)} if description.strip() else {}
        files = [(clean(file) or "sample.mp3", data) for file, data in samples]
        body, kind = _multipart(fields, files)
        headers = {"xi-api-key": str(self._api_key), "Content-Type": kind}
        out = self._open_json(urllib.request.Request(VOICES_ADD_URL, data=body, headers=headers))
        voice = str(out.get("voice_id") or "")
        if not voice:
            raise RuntimeError("ElevenLabs gave no voice_id for the clone")
        log.info(
            "elevenlabs: cloned %s as %s from %d samples (verification: %s)",
            fields["name"],
            voice,
            len(files),
            out.get("requires_verification"),
        )
        return voice

    def delete_voice(self, voice_id: str) -> None:
        """Remove a voice from the account (``DELETE /v1/voices/{voice_id}``)."""
        headers = {"xi-api-key": str(self._api_key)}
        request = urllib.request.Request(
            f"{VOICES_URL}/{voice_id}", headers=headers, method="DELETE"
        )
        with urllib.request.urlopen(request, timeout=30):
            log.info("elevenlabs: deleted voice %s", voice_id)

    def _submit_live(self, req: JobRequest, spec: ModelSpec) -> ProviderJobRef:
        model = self._catalog.endpoint_for(spec.id) or "eleven_flash_v2_5"
        text = str(req.inputs.get("prompt") or req.inputs.get("text") or "")
        seconds = float(req.inputs.get("duration") or 0)  # a cue's length; 0: the model picks
        payload: dict[str, object]
        clone = ""  # a voice_clone job's own clone, deleted after it speaks
        if req.capability == Capability.SFX:
            url, payload = SFX_URL, {"text": text, "model_id": model}
            payload |= {"duration_seconds": min(max(seconds, 0.5), 30.0)} if seconds else {}
        elif req.capability == Capability.MUSIC:  # an instrumental cue, to play under dialogue
            url, payload = MUSIC_URL, {"prompt": text, "model_id": model}
            payload["force_instrumental"] = True
            if seconds:
                payload["music_length_ms"] = int(min(max(seconds, 3.0), 600.0) * 1000)
        elif req.capability == Capability.VOICE_CLONE:
            # Clone the reference, speak the prompt in it, then delete it: a job must not use up
            # the voice slots. A clone to keep is made from the Studio (POST /olf/voice/clone).
            clone = self.clone_voice(
                f"Vinci clone {uuid.uuid4().hex[:8]}", [_reference_audio(req.inputs)]
            )
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{clone}"
            payload = {"text": text, "model_id": CLONE_TTS_MODEL}
        else:
            voice = str(req.inputs.get("voice_id") or os.environ.get("ELEVENLABS_VOICE_ID") or "")
            if not voice:  # ElevenLabs has no voice named "default": the call would fail
                raise ValueError("no ElevenLabs voice: send voice_id (or set ELEVENLABS_VOICE_ID)")
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice}"
            payload = {"text": text, "model_id": model}
        headers = {
            "xi-api-key": str(self._api_key),
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        try:
            raw = self._post_bytes(url, headers, payload)
        finally:
            if clone:
                try:
                    self.delete_voice(clone)
                except Exception as exc:  # noqa: BLE001 - the audio is made; say the slot is held
                    log.warning("elevenlabs: could not delete clone %s: %s", clone, exc)
        if not raw:
            raise RuntimeError("elevenlabs submit empty audio")
        mime = "audio/mpeg"
        if raw[:4] == b"RIFF":
            mime = "audio/wav"
        b64 = base64.b64encode(raw).decode("ascii")
        ref = str(uuid.uuid4())
        self._jobs[ref] = JobStatus(
            state=JobState.COMPLETED,
            outputs=[f"data:{mime};base64,{b64}"],
            progress=1.0,
        )
        return ProviderJobRef(provider="elevenlabs", ref=ref)
