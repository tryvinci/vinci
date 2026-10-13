from __future__ import annotations

import json

from vinci_storage.cas import ContentAddressedStore
from vinci_storage.r2_client import R2Client


class R2ContentAddressedStore:
    """CAS blobs in private R2; same digest layout as local CAS."""

    def __init__(self, client: R2Client, prefix: str = "cas") -> None:
        self.client = client
        self.prefix = prefix.rstrip("/")

    @staticmethod
    def digest(data: bytes) -> str:
        return ContentAddressedStore.digest(data)

    def _key(self, digest: str) -> str:
        digest = digest.lower()
        return f"{self.prefix}/{digest[:2]}/{digest[2:4]}/{digest}"

    def put(self, data: bytes) -> str:
        digest = self.digest(data)
        key = self._key(digest)
        if self.client.get_bytes(key) is None:
            self.client.put_bytes(key, data)
        return digest

    def get(self, digest: str) -> bytes:
        raw = self.client.get_bytes(self._key(digest))
        if raw is None:
            raise FileNotFoundError(digest)
        return raw

    def exists(self, digest: str) -> bool:
        return self.client.get_bytes(self._key(digest)) is not None

    def put_json(self, payload: object) -> str:
        blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        return self.put(blob)
