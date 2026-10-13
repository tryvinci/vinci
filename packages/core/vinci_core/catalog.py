from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import Any

from vinci_protocol.models import ModelSpec

SORA_MARKERS = ("sora", "sora-2", "sora2")
BUNDLED_CATALOGS = (
    "mock",
    "wavespeed",
    "google",
    "openai",
    "fal",
    "elevenlabs",
    "cloudflare",
    "higgsfield",
    "magnific",
)


def reject_sunset_defaults(model_id: str) -> None:
    lowered = model_id.lower()
    if any(marker in lowered for marker in SORA_MARKERS):
        raise ValueError(
            f"{model_id} is excluded from the default catalog (Sora API sunsets 2026-09-24)"
        )


@dataclass
class Catalog:
    models: list[ModelSpec]
    snapshot_id: str
    endpoints: dict[str, str] = field(default_factory=dict)
    source: str = "bundled"

    def by_id(self, model_id: str) -> ModelSpec:
        for model in self.models:
            if model.id == model_id:
                return model
        raise KeyError(model_id)

    def by_capability(self, capability: str) -> list[ModelSpec]:
        return [m for m in self.models if capability in [c.value for c in m.capabilities]]

    def cheapest(self, capability: str) -> ModelSpec | None:
        candidates = [
            m
            for m in self.by_capability(capability)
            if m.status.value == "active" and m.pricing.currency.upper() == "USD"
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda m: m.pricing.amount)

    def endpoint_for(self, model_id: str) -> str | None:
        return self.endpoints.get(model_id)


def _document_from_text(text: str, *, allow_sora: bool, source: str) -> Catalog:
    raw = json.loads(text)
    models = [ModelSpec.model_validate(item) for item in raw["models"]]
    if not allow_sora:
        for model in models:
            reject_sunset_defaults(model.id)
    endpoints = {str(k): str(v) for k, v in (raw.get("endpoints") or {}).items()}
    return Catalog(
        models=models,
        snapshot_id=str(raw.get("snapshot_id", "unknown")),
        endpoints=endpoints,
        source=source,
    )


def load_catalog(path: Path | None = None, *, allow_sora: bool = False) -> Catalog:
    if path is None:
        text = (files("vinci_core") / "catalogs" / "mock.json").read_text(encoding="utf-8")
        source = "mock"
    else:
        text = path.read_text(encoding="utf-8")
        source = path.name
    return _document_from_text(text, allow_sora=allow_sora, source=source)


def load_bundled_catalog(name: str, *, allow_sora: bool = False) -> Catalog:
    text = (files("vinci_core") / "catalogs" / f"{name}.json").read_text(encoding="utf-8")
    return _document_from_text(text, allow_sora=allow_sora, source=name)


def merge_catalogs(catalogs: list[Catalog]) -> Catalog:
    models: list[ModelSpec] = []
    endpoints: dict[str, str] = {}
    ids: list[str] = []
    for catalog in catalogs:
        models.extend(catalog.models)
        endpoints.update(catalog.endpoints)
        ids.append(catalog.snapshot_id)
    return Catalog(models=models, snapshot_id="+".join(ids) or "empty", endpoints=endpoints)


def catalog_to_document(catalog: Catalog) -> dict[str, Any]:
    return {
        "snapshot_id": catalog.snapshot_id,
        "models": [m.model_dump(mode="json") for m in catalog.models],
        "endpoints": catalog.endpoints,
    }
