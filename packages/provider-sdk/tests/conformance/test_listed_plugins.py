from __future__ import annotations

import pytest
from vinci_core.paths import allow_live_spend
from vinci_provider_cloudflare import CloudflareProvider
from vinci_provider_elevenlabs import ElevenLabsProvider
from vinci_provider_fal import FalProvider
from vinci_provider_google import GoogleProvider
from vinci_provider_higgsfield import HiggsfieldProvider
from vinci_provider_magnific import MagnificProvider
from vinci_provider_openai import OpenAIProvider
from vinci_provider_sdk.base import Provider
from vinci_provider_sdk.catalog_provider import LiveSpendDisabled
from vinci_provider_sdk.conformance import run_conformance, sample_request
from vinci_provider_wavespeed import WavespeedProvider

SECRET = "sk-conformance-never-log-me"

PROVIDERS = (
    WavespeedProvider(api_key=SECRET),
    GoogleProvider(api_key=SECRET),
    OpenAIProvider(api_key=SECRET),
    FalProvider(api_key=SECRET),
    ElevenLabsProvider(api_key=SECRET),
    CloudflareProvider(api_key=SECRET, account_id="acct"),
    HiggsfieldProvider(api_key=SECRET, api_secret=SECRET),
    MagnificProvider(api_key=SECRET),
)


@pytest.mark.parametrize("provider", PROVIDERS, ids=lambda item: item.provider_id)
def test_listed_plugin_fixture_conformance(provider: Provider) -> None:
    run_conformance(provider, secret=SECRET, live_submit=False)


@pytest.mark.parametrize("provider", PROVIDERS, ids=lambda item: item.provider_id)
def test_listed_plugin_submit_requires_live_spend_flag(provider: Provider) -> None:
    assert allow_live_spend() is False
    req = sample_request(provider)
    provider.estimate(req)
    with pytest.raises(LiveSpendDisabled):
        provider.submit(req)
