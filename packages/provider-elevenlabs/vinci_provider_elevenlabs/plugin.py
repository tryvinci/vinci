from __future__ import annotations

import base64
import os
import uuid

from vinci_protocol.enums import JobState
from vinci_protocol.models import (
    JobRequest,
    JobStatus,
    ModelSpec,
    ProviderAuth,
    ProviderJobRef,
    ProviderManifest,
)
from vinci_provider_sdk.catalog_provider import CatalogBackedProvider


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

    def _submit_live(self, req: JobRequest, spec: ModelSpec) -> ProviderJobRef:
        model = self._catalog.endpoint_for(spec.id) or "eleven_flash_v2_5"
        voice = str(
            req.inputs.get("voice_id") or os.environ.get("ELEVENLABS_VOICE_ID") or "default"
        )
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice}"
        payload = {
            "text": str(req.inputs.get("prompt") or req.inputs.get("text") or ""),
            "model_id": model,
        }
        headers = {
            "xi-api-key": str(self._api_key),
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        raw = self._post_bytes(url, headers, payload)
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
