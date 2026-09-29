from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from vinci_protocol.enums import RoutePreference
from vinci_protocol.models import Estimate, JobRequest, ModelSpec, WorkflowSpec

from vinci_core.catalog import Catalog


def estimate_from_spec(
    spec: ModelSpec, unit_count: float = 1.0, *, cached: bool = False
) -> Estimate:
    amount = 0.0 if cached else spec.pricing.amount * unit_count
    return Estimate(
        model_id=spec.id,
        provider=spec.provider,
        amount=amount,
        currency=spec.pricing.currency,
        unit=spec.pricing.unit,
        unit_count=unit_count,
        pricing_snapshot_at=spec.pricing.snapshot_at,
        cached=cached,
    )


def active_candidates(catalog: Catalog, capability: str) -> list[ModelSpec]:
    return [model for model in catalog.by_capability(capability) if model.status.value == "active"]


def resolve_model(
    catalog: Catalog, req: JobRequest, *, available_providers: set[str] | None = None
) -> ModelSpec:
    if req.model_id:
        spec = catalog.by_id(req.model_id)
        if req.capability.value not in [c.value for c in spec.capabilities]:
            raise ValueError(f"{spec.id} lacks capability {req.capability}")
        return spec
    candidates = active_candidates(catalog, req.capability.value)
    if available_providers is not None:
        candidates = [m for m in candidates if m.provider in available_providers]
    if not candidates:
        raise KeyError(f"no model for {req.capability}")
    if req.preference == RoutePreference.QUALITY:
        quality = [m for m in candidates if m.quality_tier == "quality"]
        pool = quality or candidates
        return max(pool, key=lambda m: m.pricing.amount)
    if req.preference == RoutePreference.FASTEST:
        fast = [m for m in candidates if m.quality_tier == "fast"]
        pool = fast or candidates
        return min(pool, key=lambda m: m.pricing.amount)
    return min(candidates, key=lambda m: m.pricing.amount)


def with_alternative(estimate: Estimate, catalog: Catalog, capability: str) -> Estimate:
    cheap = catalog.cheapest(capability)
    if cheap is None or cheap.id == estimate.model_id:
        return estimate
    return estimate.model_copy(
        update={
            "alternative": {
                "model_id": cheap.id,
                "provider": cheap.provider,
                "amount": cheap.pricing.amount,
                "currency": cheap.pricing.currency,
            }
        }
    )


def should_await_approval(
    total: float,
    *,
    max_cost: float | None,
    monthly_spent: float,
    monthly_cap: float | None,
    require_over: float | None,
) -> str | None:
    if max_cost is not None and total > max_cost:
        return f"estimate {total} exceeds --max-cost {max_cost}"
    if monthly_cap is not None and monthly_spent + total > monthly_cap:
        return f"estimate {total} would exceed monthly cap {monthly_cap}"
    if require_over is not None and total > require_over:
        return f"estimate {total} exceeds require_approval_over {require_over}"
    return None


def plan_workflow(
    catalog: Catalog,
    spec: WorkflowSpec,
    *,
    available_providers: set[str] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for node in spec.nodes:
        if node.type.value != "generate" or node.capability is None:
            continue
        req = JobRequest(
            capability=node.capability,
            model_id=node.model_id,
            preference=spec.preference,
        )
        model = resolve_model(catalog, req, available_providers=available_providers)
        estimate = with_alternative(estimate_from_spec(model), catalog, node.capability.value)
        rows.append({"node_id": node.id, "model": model, "estimate": estimate})
    return rows


def idempotency_key(model_id: str, inputs: dict[str, object]) -> str:
    blob = json.dumps({"model_id": model_id, "inputs": inputs}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def now_utc() -> datetime:
    return datetime.now(tz=UTC)
