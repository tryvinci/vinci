from __future__ import annotations

import io
import json
import logging
from unittest import mock

import pytest
from vinci_core.catalog import load_bundled_catalog
from vinci_protocol.enums import Capability
from vinci_protocol.models import JobRequest
from vinci_provider_openai.plugin import (
    OpenAIProvider,
    _first_b64,
    _size_from_inputs,
)
from vinci_provider_sdk.catalog_provider import LiveSpendDisabled
from vinci_provider_sdk.conformance import run_conformance

SECRET = "openai-conformance-redact-token-value"


class _MemCas:
    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {"abc": b"\x89PNG\r\n\x1a\n"}

    def get(self, digest: str) -> bytes:
        return self._blobs[digest]

    def put(self, data: bytes) -> str:
        digest = f"out-{len(data)}"
        self._blobs[digest] = data
        return digest


def test_openai_catalog_models_and_pricing_snapshot() -> None:
    catalog = load_bundled_catalog("openai")
    assert catalog.snapshot_id == "openai-2026-09-28"
    ids = {m.id for m in catalog.models}
    assert "openai:gpt-image-2.5-flare:2026-09" in ids
    assert "openai:gpt-image-2.5-sunburst:2026-09" in ids
    flare = catalog.by_id("openai:gpt-image-2.5-flare:2026-09")
    assert Capability.T2I in flare.capabilities
    assert flare.pricing.unit == "token"
    assert flare.pricing.amount == 0.0
    assert "2048x2048" not in flare.constraints.resolutions
    assert flare.secret_names == ["OPENAI_API_KEY"]


def test_openai_estimate_without_key() -> None:
    provider = OpenAIProvider()
    req = JobRequest(capability=Capability.T2I, inputs={"prompt": "cube"})
    est = provider.estimate(req)
    assert est.amount == 0.0
    assert est.unit == "token"


def test_openai_submit_requires_key_and_live_spend() -> None:
    provider = OpenAIProvider(api_key=None, cas=_MemCas())
    req = JobRequest(capability=Capability.T2I, inputs={"prompt": "cube"})
    provider.estimate(req)
    with pytest.raises(PermissionError):
        provider.submit(req)

    provider = OpenAIProvider(api_key=SECRET, cas=_MemCas())
    provider.estimate(req)
    with pytest.raises(LiveSpendDisabled):
        provider.submit(req)


def test_openai_conformance_offline() -> None:
    run_conformance(OpenAIProvider(api_key=SECRET), secret=SECRET, live_submit=False)


def test_openai_secret_redaction_in_logs() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger("vinci.provider")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    provider = OpenAIProvider(api_key=SECRET, cas=_MemCas())
    req = JobRequest(capability=Capability.T2I, inputs={"prompt": "cube", "note": SECRET})
    provider.estimate(req)
    try:
        provider.submit(req)
    except LiveSpendDisabled:
        pass
    logger.removeHandler(handler)
    assert SECRET not in stream.getvalue()


def test_openai_parse_generation_response() -> None:
    body = {"data": [{"b64_json": "aGVsbG8="}]}
    assert _first_b64(body) == "aGVsbG8="


def test_openai_size_mapping() -> None:
    assert _size_from_inputs({"aspect_ratio": "16:9"}) == "1536x1024"
    assert _size_from_inputs({"size": "1024x1536"}) == "1024x1536"


def test_openai_live_submit_uses_mocked_http() -> None:
    cas = _MemCas()
    provider = OpenAIProvider(api_key=SECRET, cas=cas)
    req = JobRequest(capability=Capability.T2I, inputs={"prompt": "red cube"})
    provider.estimate(req)
    fake_png = b"\x89PNG\r\n\x1a\n"
    payload = json.dumps({"data": [{"b64_json": "aGVsbG8="}]}).encode()

    class FakeResp:
        def read(self) -> bytes:
            return payload

        def __enter__(self) -> FakeResp:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    with (
        mock.patch("vinci_provider_sdk.catalog_provider.allow_live_spend", return_value=True),
        mock.patch("urllib.request.urlopen", return_value=FakeResp()),
        mock.patch(
            "vinci_provider_openai.plugin.base64.b64decode",
            return_value=fake_png,
        ),
    ):
        ref = provider.submit(req)
    status = provider.status(ref)
    assert status.state.value == "completed"
    assert status.outputs
