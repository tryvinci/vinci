from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Protocol


class CasStore(Protocol):
    def put(self, data: bytes) -> str: ...

    def get(self, digest: str) -> bytes: ...

    def exists(self, digest: str) -> bool: ...


class ContentAddressedStore:
    """SHA-256 content-addressed files under ``{root}/{aa}/{bb}/{digest}``."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def digest(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def put(self, data: bytes) -> str:
        digest = self.digest(data)
        path = self._path(digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, path)
        return digest

    def get(self, digest: str) -> bytes:
        path = self._path(digest)
        if not path.is_file():
            raise FileNotFoundError(digest)
        return path.read_bytes()

    def exists(self, digest: str) -> bool:
        return self._path(digest).is_file()

    def put_json(self, payload: object) -> str:
        blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        return self.put(blob)

    def _path(self, digest: str) -> Path:
        if len(digest) < 8 or any(c not in "0123456789abcdef" for c in digest.lower()):
            raise ValueError("digest must be sha256 hex")
        digest = digest.lower()
        return self.root / digest[:2] / digest[2:4] / digest
