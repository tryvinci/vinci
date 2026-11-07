"""A live model with amount 0 is unpriced, not free: rank it last (COREPRODUC-529).

OpenAI image models bill per token, so their catalog amount is 0. "cheapest" used to rank
them first, and an invalid OpenAI key then failed every run with a bare HTTP 401.
Offline: the HTTP layer is replaced and every key is fake.
"""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from typing import Any

import pytest
from vinci_core.catalog import Catalog, load_bundled_catalog, merge_catalogs
from vinci_core.cost import resolve_model
from vinci_protocol.enums import Capability, RoutePreference
from vinci_protocol.models import JobRequest
from vinci_runtime.engine import (
    Engine,
    all_secret_names,
    auth_rejected_message,
    provider_error_detail,
)

PREFERENCES = [RoutePreference.CHEAPEST, RoutePreference.FASTEST]


def _catalog(*names: str) -> Catalog:
    """Merge the bundled catalogs of the named providers."""
    return merge_catalogs([load_bundled_catalog(name) for name in names])


def _pick(catalog: Catalog, preference: RoutePreference, **kwargs: Any) -> Any:
    """Resolve a t2i request with no pinned model."""
    req = JobRequest(capability=Capability.T2I, preference=preference)
    return resolve_model(catalog, req, **kwargs)


@pytest.mark.parametrize("preference", PREFERENCES)
def test_unpriced_openai_ranks_after_a_priced_model(preference: RoutePreference) -> None:
    """Cheapest and fastest pick a priced Wavespeed model over the $0 OpenAI rows."""
    catalog = _catalog("openai", "wavespeed")
    model = _pick(catalog, preference)
    assert model.provider == "wavespeed"
    assert model.pricing.amount > 0
    cheapest = catalog.cheapest("t2i")
    assert cheapest is not None and cheapest.provider == "wavespeed"


@pytest.mark.parametrize("preference", PREFERENCES)
def test_unpriced_models_still_route_when_nothing_else_exists(
    preference: RoutePreference,
) -> None:
    """With nothing priced to prefer, an unpriced model still routes."""
    assert _pick(_catalog("openai"), preference).provider == "openai"


@pytest.mark.parametrize("preference", PREFERENCES)
def test_mock_stays_free_and_first_in_demo_mode(preference: RoutePreference) -> None:
    """Mock is free by design, so it still wins in demo mode."""
    assert _pick(_catalog("mock", "openai", "wavespeed"), preference).provider == "mock"


def _use_keys(monkeypatch: pytest.MonkeyPatch, home: Path, **keys: str) -> Engine:
    """Engine in live mode with only the given fake keys set and live spend on."""
    monkeypatch.setenv("VINCI_HOME", str(home))
    for name in all_secret_names():
        monkeypatch.delenv(name, raising=False)
    for name, value in keys.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("VINCI_ALLOW_LIVE_SPEND", "1")
    engine = Engine(home)
    engine.init_home(demo=False)
    return engine


def test_missing_openai_key_is_never_routed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No key means not available, so only an INVALID key can reach OpenAI and fail."""
    engine = _use_keys(monkeypatch, tmp_path, WAVESPEED_API_KEY="fake-wavespeed-key")
    assert engine.routing_providers() == {"wavespeed"}
    model = _pick(
        engine.catalog(),
        RoutePreference.CHEAPEST,
        available_providers=engine.routing_providers(),
    )
    assert model.provider == "wavespeed"


# 403 body: a valid key without model access (OpenAI asks for org verification on image models).
_FORBIDDEN = b'{"error": {"message": "Key sk-fake-invalid-key: your organization must be verified"}}'


@pytest.mark.parametrize(
    ("code", "body", "expected"),
    [
        (401, b"{}", "openai rejected its API key (HTTP 401). Check OPENAI_API_KEY in Connect."),
        (
            403,
            _FORBIDDEN,
            "openai refused the request (HTTP 403): Key [redacted]: your organization must be "
            "verified. Check the account and model access.",
        ),
        (500, b"{}", None),
    ],
)
def test_provider_auth_error_names_the_provider_and_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int, body: bytes, expected: str | None
) -> None:
    """A 401 names the key; a 403 shows the provider's redacted reason; others pass through."""
    engine = _use_keys(monkeypatch, tmp_path, OPENAI_API_KEY="sk-fake-invalid-key")

    def fake_urlopen(request: Any, timeout: int = 30) -> Any:
        url = getattr(request, "full_url", str(request))
        assert "api.openai.com" in url, f"unexpected network call: {url}"
        raise urllib.error.HTTPError(url, code, "denied", Message(), io.BytesIO(body))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(RuntimeError if expected else urllib.error.HTTPError) as err:
        engine.start_run("@tryvinci/image-generate", {"prompt": "a cat"})
    if expected:
        assert str(err.value) == expected
    assert "sk-fake-invalid-key" not in str(err.value)


@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        ("openai", "openai rejected its API key (HTTP 401). Check OPENAI_API_KEY in Connect."),
        (
            "higgsfield",
            "higgsfield rejected its API key (HTTP 401). "
            "Check HIGGSFIELD_API_KEY and HIGGSFIELD_API_SECRET in Connect.",
        ),
        # An MCP server may use OAuth, a per-server key, or MCP_API_KEY: name none of them.
        ("mcp_magnific", "mcp_magnific rejected its credentials (HTTP 401). Reconnect it in Connect."),
    ],
)
def test_auth_rejected_message_names_only_known_keys(provider: str, expected: str) -> None:
    """Built-in providers name their keys; an MCP server gets a generic message."""
    assert auth_rejected_message(provider, 401) == expected


@pytest.mark.parametrize("provider", ["openai", "mcp_magnific"])
def test_403_does_not_blame_the_key(provider: str) -> None:
    """A 403 can come with a valid key, so the message names no key (PR-Agent review on #513)."""
    text = auth_rejected_message(provider, 403)
    assert text == f"{provider} refused the request (HTTP 403). Check the account and model access."


def test_403_detail_redacts_a_key_that_crosses_the_cut() -> None:
    """Redaction runs before the 200-character cut, so no part of a key leaks (PR-Agent, Opus 5.5)."""
    key = "zz-fake-0123456789abcdef"  # not key-shaped, so the secret scan passes
    message = "x" * 190 + key
    body = io.BytesIO(json.dumps({"error": {"message": message}}).encode())
    err = urllib.error.HTTPError("https://api.example", 403, "denied", Message(), body)
    detail = provider_error_detail(err, [key])
    assert "zz-fake" not in detail and len(detail) <= 200
