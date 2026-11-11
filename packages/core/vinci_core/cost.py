from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from vinci_protocol.enums import RoutePreference
from vinci_protocol.models import Estimate, JobRequest, ModelSpec, WorkflowSpec

from vinci_core.catalog import Catalog, price_key


def asked_seconds(value: Any, inputs: Mapping[str, Any] | None = None) -> float | None:
    """A job's clip length in seconds: a number, or an ``{{inputs.name}}`` that the run fills.

    Args:
        value: The node's or the request's ``duration``.
        inputs: The run inputs, for a template.

    Returns:
        The length, or None when there is none (the model's default clip).
    """
    match = re.fullmatch(r"\{\{\s*inputs\.(\w+)\s*\}\}", value) if isinstance(value, str) else None
    if match:
        value = (inputs or {}).get(match.group(1))
    if isinstance(value, bool):
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return seconds if math.isfinite(seconds) and seconds > 0 else None


def clip_price(spec: ModelSpec, seconds: float | None = None) -> float:
    """The list price of one job on ``spec``.

    A row with ``clip_prices`` bills the clip length the model makes: the asked length fitted with
    ``fit_duration``, as the runtime sends it. With no length, or one the table lacks, it is
    ``amount``, the price of the default clip (COREPRODUC-555).

    Args:
        spec: The model row.
        seconds: The asked clip length, or None.
    """
    table = spec.pricing.clip_prices
    if not table or seconds is None:
        return spec.pricing.amount
    return table.get(str(fit_duration(seconds, spec.constraints)), spec.pricing.amount)


def estimate_from_spec(
    spec: ModelSpec,
    unit_count: float = 1.0,
    *,
    cached: bool = False,
    seconds: float | None = None,
) -> Estimate:
    amount = 0.0 if cached else clip_price(spec, seconds) * unit_count
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
    """Pick the model a request runs on.

    A pinned `req.model_id` wins. Otherwise the preference ranks the active USD candidates,
    and an unpriced model ranks after priced ones (see `price_key`).

    Args:
        catalog: The active catalog.
        req: The request. `model_id`, `capability`, and `preference` drive the choice.
        available_providers: When set, only models of these providers can win.

    Returns:
        The chosen model spec.

    Raises:
        ValueError: A pinned model lacks the requested capability.
        KeyError: A pinned model is not in the catalog, or no model fits.
    """
    if req.model_id:
        spec = catalog.by_id(req.model_id)
        if req.capability.value not in [c.value for c in spec.capabilities]:
            raise ValueError(f"{spec.id} lacks capability {req.capability}")
        return spec
    candidates = active_candidates(catalog, req.capability.value)
    if available_providers is not None:
        candidates = [m for m in candidates if m.provider in available_providers]
    candidates = [m for m in candidates if m.pricing.currency.upper() == "USD"]
    if not candidates:
        raise KeyError(f"no model for {req.capability}")
    if req.preference == RoutePreference.QUALITY:
        quality = [m for m in candidates if m.quality_tier == "quality"]
        pool = quality or candidates
        return max(pool, key=lambda m: m.pricing.amount)
    if req.preference == RoutePreference.FASTEST:
        fast = [m for m in candidates if m.quality_tier == "fast"]
        pool = fast or candidates
        return min(pool, key=price_key)
    return min(candidates, key=price_key)


def with_alternative(
    estimate: Estimate, catalog: Catalog, capability: str, seconds: float | None = None
) -> Estimate:
    """Name the cheapest model for ``capability`` next to an estimate, priced at the same clip
    length (``seconds``) as the estimate (COREPRODUC-555)."""
    cheap = catalog.cheapest(capability)
    if cheap is None or cheap.id == estimate.model_id:
        return estimate
    return estimate.model_copy(
        update={
            "alternative": {
                "model_id": cheap.id,
                "provider": cheap.provider,
                "amount": clip_price(cheap, seconds),
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
    inputs: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Route each generate node and price it; a clip is priced by the node's ``duration``.

    Args:
        catalog: The active catalog.
        spec: The workflow.
        available_providers: When set, only models of these providers can win.
        inputs: The run inputs, for a ``{{inputs.duration}}`` param.
    """
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
        seconds = asked_seconds(node.params.get("duration"), inputs)
        estimate = with_alternative(
            estimate_from_spec(model, seconds=seconds), catalog, node.capability.value, seconds
        )
        rows.append({"node_id": node.id, "model": model, "estimate": estimate})
    return rows


def fit_duration(seconds: float, constraints: Any) -> float:
    """Return the clip length to ask a video model for.

    The shortest length the model takes (``constraints.durations``, from its API docs, kept as
    listed: 2.5 stays 2.5) that covers the ask, else its longest. A model with only
    ``max_duration`` gets the ask rounded up, capped there. A whole number comes back as an int.
    Used by the OLF render (a shot's length) and by the runtime (a job's ``duration`` that the
    model would refuse, COREPRODUC-580).

    Args:
        seconds: The length asked for.
        constraints: The model's ``ModelConstraints``, or None.
    """
    allowed = sorted(float(d) for d in (getattr(constraints, "durations", None) or []))
    if allowed:
        picked = next((d for d in allowed if d >= seconds), allowed[-1])
        return int(picked) if picked.is_integer() else picked
    want = math.ceil(seconds)
    cap = getattr(constraints, "max_duration", None)
    return min(want, int(cap)) if cap else want


def idempotency_key(model_id: str, inputs: dict[str, object]) -> str:
    blob = json.dumps({"model_id": model_id, "inputs": inputs}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def now_utc() -> datetime:
    return datetime.now(tz=UTC)
