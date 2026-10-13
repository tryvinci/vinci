from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from vinci_core.config import VinciConfig

try:
    import keyring as keyring_mod
except ImportError:
    keyring_mod = None


class SecretBackend(Protocol):
    def get(self, name: str) -> str | None: ...

    def set(self, name: str, value: str) -> None: ...

    def delete(self, name: str) -> None: ...


class EnvBackend:
    def get(self, name: str) -> str | None:
        value = os.environ.get(name)
        return value if value else None

    def set(self, name: str, value: str) -> None:
        os.environ[name] = value

    def delete(self, name: str) -> None:
        os.environ.pop(name, None)


class KeychainBackend:
    """OS keychain via optional `keyring`. Missing library → no-op."""

    SERVICE = "vinci"

    def get(self, name: str) -> str | None:
        if keyring_mod is None:
            return None
        value = keyring_mod.get_password(self.SERVICE, name)
        return value if value else None

    def set(self, name: str, value: str) -> None:
        if keyring_mod is None:
            raise RuntimeError("keyring is not installed")
        keyring_mod.set_password(self.SERVICE, name, value)

    def delete(self, name: str) -> None:
        if keyring_mod is None:
            return
        try:
            keyring_mod.delete_password(self.SERVICE, name)
        except Exception:
            return


class FileBackend:
    """Local secrets under `$VINCI_HOME/keys/` (0600). Used when the OS keychain is absent."""

    def __init__(self, home: Path | None) -> None:
        self._dir = (home / "keys") if home else None

    def get(self, name: str) -> str | None:
        path = self._key_path(name)
        if path is None or not path.is_file():
            return None
        return path.read_text(encoding="utf-8").strip() or None

    def set(self, name: str, value: str) -> None:
        path = self._key_path(name)
        if path is None:
            raise RuntimeError("VINCI_HOME is not set; cannot store a file secret")
        path.parent.mkdir(mode=0o700, exist_ok=True)
        path.parent.chmod(0o700)
        path.write_text(value, encoding="utf-8")
        path.chmod(0o600)

    def delete(self, name: str) -> None:
        path = self._key_path(name)
        if path is None or not path.is_file():
            return
        path.unlink()

    def _key_path(self, name: str) -> Path | None:
        if self._dir is None:
            return None
        if not name.isidentifier() or Path(name).name != name:
            raise ValueError("secret_name must be an identifier")
        return self._dir / name


class ConfigRefBackend:
    """Resolve `secrets.NAME = "env:FOO"` refs from config.toml. Never stores raw keys in git."""

    def __init__(self, refs: Mapping[str, str], home: Path | None = None) -> None:
        self._refs = dict(refs)
        self._home = home

    def get(self, name: str) -> str | None:
        ref = self._refs.get(name)
        if not ref:
            return None
        if ref.startswith("env:"):
            return os.environ.get(ref[4:]) or None
        if ref.startswith("file:"):
            path = Path(ref[5:]).expanduser()
            if not path.is_absolute() and self._home is not None:
                path = self._home / path
            if path.is_file():
                return path.read_text(encoding="utf-8").strip() or None
        return None

    def set(self, name: str, value: str) -> None:
        raise RuntimeError("config refs are not writable; use keychain or env")

    def delete(self, name: str) -> None:
        return


class CredentialResolver:
    """Resolve provider secret *names* from keychain → file → env → config refs.

    Values never belong in job records. Callers must pass names, not payloads.
    """

    def __init__(self, config: VinciConfig | None = None) -> None:
        self._config = config
        refs = config.secrets if config else {}
        home = config.home if config else None
        self._file = FileBackend(home)
        self._chain: list[SecretBackend] = [
            KeychainBackend(),
            self._file,
            EnvBackend(),
            ConfigRefBackend(refs, home=home),
        ]

    def put(self, secret_name: str, value: str) -> str:
        """Store a provider key in the OS keychain, or `$VINCI_HOME/keys/` if keyring is missing."""
        if not secret_name.isidentifier():
            raise ValueError("secret_name must be an identifier, not a value")
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("empty secret")
        try:
            KeychainBackend().set(secret_name, trimmed)
            return "keychain"
        except Exception:
            self._file.set(secret_name, trimmed)
            return "file"

    def resolve(self, secret_name: str) -> str | None:
        if not secret_name or secret_name != secret_name.upper() and "=" in secret_name:
            raise ValueError("secret_name must be an identifier, not a value")
        for backend in self._chain:
            value = backend.get(secret_name)
            if value:
                return value
        return None

    def delete(self, secret_name: str) -> None:
        if not secret_name.isidentifier():
            raise ValueError("secret_name must be an identifier, not a value")
        KeychainBackend().delete(secret_name)
        self._file.delete(secret_name)

    def require(self, secret_name: str) -> str:
        value = self.resolve(secret_name)
        if not value:
            raise KeyError(f"missing secret {secret_name}")
        return value

    def known_values(self, names: list[str]) -> list[str]:
        values: list[str] = []
        for name in names:
            value = self.resolve(name)
            if value:
                values.append(value)
        return values
