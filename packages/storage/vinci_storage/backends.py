from __future__ import annotations

import os
from pathlib import Path

from vinci_storage.cas import CasStore, ContentAddressedStore
from vinci_storage.r2_cas import R2ContentAddressedStore
from vinci_storage.r2_client import R2Client


def make_cas(cas_dir: Path) -> CasStore:
    mode = os.environ.get("VINCI_CAS_BACKEND", "local").lower()
    if mode == "local":
        return ContentAddressedStore(cas_dir)
    if mode == "r2":
        client = R2Client.from_env()
        if client is None:
            raise RuntimeError("VINCI_CAS_BACKEND=r2 requires R2 env vars or VINCI_R2_MOCK_DIR")
        prefix = os.environ.get("VINCI_R2_CAS_PREFIX", "cas")
        return R2ContentAddressedStore(client, prefix=prefix)
    raise ValueError(f"unknown VINCI_CAS_BACKEND: {mode}")
