"""Text models (``t2t``, COREPRODUC-548): catalog rows, the mock, and the OpenAI and Google calls."""

from __future__ import annotations

import base64
import json
from typing import Any
from unittest import mock

from vinci_core.catalog import load_bundled_catalog, price_key
from vinci_protocol.enums import Capability
from vinci_protocol.models import JobRequest

SECRET = "text-model-test-key"


class _MemCas:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    def get(self, digest: str) -> bytes:
        return self.blobs[digest]

    def put(self, data: bytes) -> str:
        self.blobs[f"d{len(self.blobs)}"] = data
        return f"d{len(self.blobs) - 1}"


def test_catalog_rows_are_token_billed_text_models() -> None:
    rows = {
        "openai": "openai:gpt-6-luna:2026-11",  # developers.openai.com/api/docs/models, 2026-11-09
        "google": "google:gemini-3.8-flash:2026-09",  # ai.google.dev: stable model code
        "mock": "mock:llm:v1",
    }
    for name, model_id in rows.items():
        spec = load_bundled_catalog(name).by_id(model_id)
        assert spec.capabilities == [Capability.T2T]
        # Token billing has no flat price: the Studio asks first; the mock is a $0 price.
        assert bool(price_key(spec)[0]) == (name != "mock"), model_id


def test_mock_text_model_answers_the_expected_reply(tmp_path: Any) -> None:
    from vinci_provider_sdk.mock import MockProvider
    from vinci_storage.cas import ContentAddressedStore

    cas = ContentAddressedStore(tmp_path)
    provider = MockProvider(cas)
    req = JobRequest(
        capability=Capability.T2T,
        model_id="mock:llm:v1",
        inputs={"prompt": "an idea", "mock_reply": "INT. ROOM - DAY\n"},
    )
    provider.estimate(req)
    status = provider.status(provider.submit(req))
    assert cas.get(status.outputs[0]) == b"INT. ROOM - DAY\n"
    plain = JobRequest(capability=Capability.T2T, model_id="mock:llm:v1", inputs={"prompt": "hi"})
    provider.estimate(plain)
    assert cas.get(provider.status(provider.submit(plain)).outputs[0]).startswith(b"Mock reply")


class _Reply:
    def __init__(self, body: dict[str, Any]) -> None:
        self.body = json.dumps(body).encode()

    def read(self) -> bytes:
        return self.body

    def __enter__(self) -> _Reply:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_openai_text_uses_the_responses_api() -> None:
    from vinci_provider_openai.plugin import OpenAIProvider

    cas = _MemCas()
    provider = OpenAIProvider(api_key=SECRET, cas=cas)
    req = JobRequest(
        capability=Capability.T2T,
        model_id="openai:gpt-6-luna:2026-11",
        inputs={"prompt": "Split this script.", "system": "You turn scripts into shots."},
    )
    provider.estimate(req)
    body = {  # the shape on developers.openai.com/api/reference/resources/responses
        "status": "completed",
        "output": [
            {"type": "reasoning", "summary": []},
            {"type": "message", "content": [{"type": "output_text", "text": "[WS 24mm 3s] Dawn."}]},
        ],
    }
    sent: list[Any] = []

    def fake_urlopen(request: Any, timeout: int = 0) -> _Reply:
        sent.append(request)
        return _Reply(body)

    with (
        mock.patch("vinci_provider_sdk.catalog_provider.allow_live_spend", return_value=True),
        mock.patch("urllib.request.urlopen", side_effect=fake_urlopen),
    ):
        status = provider.status(provider.submit(req))
    assert sent[0].full_url == "https://api.openai.com/v1/responses"
    payload = json.loads(sent[0].data)
    assert payload == {
        "model": "gpt-6-luna",
        "input": "Split this script.",
        "instructions": "You turn scripts into shots.",
    }
    assert cas.get(status.outputs[0]) == b"[WS 24mm 3s] Dawn."


def test_google_text_returns_the_answer_without_thoughts() -> None:
    from vinci_provider_google.plugin import GoogleProvider

    provider = GoogleProvider(api_key=SECRET)
    req = JobRequest(
        capability=Capability.T2T,
        model_id="google:gemini-3.8-flash:2026-09",
        inputs={"prompt": "Draft a script.", "system": "Reply in Fountain."},
    )
    provider.estimate(req)
    parts = [{"text": "thinking...", "thought": True}, {"text": "EXT. CLIFF - DUSK"}]
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_post(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        calls.append((url, payload))
        return {"responseId": "r1", "candidates": [{"content": {"parts": parts}}]}

    with (
        mock.patch("vinci_provider_sdk.catalog_provider.allow_live_spend", return_value=True),
        mock.patch.object(provider, "_post_json", side_effect=fake_post),
    ):
        status = provider.status(provider.submit(req))
    url, payload = calls[0]
    assert url.endswith("/v1beta/models/gemini-3.8-flash:generateContent")
    assert payload["systemInstruction"] == {"parts": [{"text": "Reply in Fountain."}]}
    data = status.outputs[0]
    assert data.startswith("data:text/plain;base64,")
    assert base64.b64decode(data.split(",", 1)[1]) == b"EXT. CLIFF - DUSK"
