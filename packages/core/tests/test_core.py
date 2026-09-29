from pathlib import Path

import pytest
from vinci_core.catalog import load_catalog, reject_sunset_defaults
from vinci_core.config import VinciConfig
from vinci_core.credentials import CredentialResolver
from vinci_core.redact import redact_mapping


def test_mock_catalog_has_no_sora() -> None:
    catalog = load_catalog()
    assert catalog.models
    for model in catalog.models:
        assert "sora" not in model.id.lower()


def test_reject_sora() -> None:
    with pytest.raises(ValueError, match="excluded"):
        reject_sunset_defaults("openai:sora-2:pro")


def test_credential_resolver_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_API_KEY", "env-value")
    resolver = CredentialResolver()
    assert resolver.resolve("MOCK_API_KEY") == "env-value"


def test_credential_resolver_keychain_beats_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MOCK_API_KEY", "env-value")
    monkeypatch.setenv("FILE_SECRET", "config-value")

    def fake_get(self: object, name: str) -> str | None:
        return "keychain-value" if name == "MOCK_API_KEY" else None

    monkeypatch.setattr("vinci_core.credentials.KeychainBackend.get", fake_get)
    config = VinciConfig(home=tmp_path, secrets={"MOCK_API_KEY": "env:FILE_SECRET"})
    resolver = CredentialResolver(config)
    assert resolver.resolve("MOCK_API_KEY") == "keychain-value"
    monkeypatch.setattr(
        "vinci_core.credentials.KeychainBackend.get", lambda self, name: None
    )
    env_first = CredentialResolver(config)
    assert env_first.resolve("MOCK_API_KEY") == "env-value"
    monkeypatch.delenv("MOCK_API_KEY")
    config_last = CredentialResolver(config)
    assert config_last.resolve("MOCK_API_KEY") == "config-value"


def test_file_backend_put_and_resolve(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WAVESPEED_API_KEY", raising=False)
    config = VinciConfig(home=tmp_path)
    resolver = CredentialResolver(config)
    kind = resolver.put("WAVESPEED_API_KEY", "file-stored-provider-key")
    assert kind in {"file", "keychain"}
    assert resolver.resolve("WAVESPEED_API_KEY") == "file-stored-provider-key"
    if kind == "file":
        path = tmp_path / "keys" / "WAVESPEED_API_KEY"
        assert path.is_file()
        assert path.stat().st_mode & 0o777 == 0o600
    dumped = redact_mapping(
        {"prompt": "cat", "note": "file-stored-provider-key"},
        extra_values=["file-stored-provider-key"],
    )
    assert dumped["note"] == "[redacted]"


def test_redact_secret_keys_and_values() -> None:
    payload = {"prompt": "cat", "api_key": "xyz", "note": "xyz"}
    out = redact_mapping(payload, extra_values=["xyz"])
    assert out["api_key"] == "[redacted]"
    assert out["note"] == "[redacted]"
    assert out["prompt"] == "cat"
