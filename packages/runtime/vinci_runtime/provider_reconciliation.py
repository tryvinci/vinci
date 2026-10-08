"""Provider job ref recovery: ledger + status poll vs fail-closed resubmit."""

from __future__ import annotations

import json
from typing import Any, cast

from vinci_protocol.enums import ErrorCode, JobState
from vinci_protocol.models import JobStatus, ProviderJobRef


class ProviderInflightUncertain(RuntimeError):
    """Ledger records a provider ref but the vendor cannot be reconciled safely."""


def supports_durable_reconciliation(provider: Any) -> bool:
    """Whether status(ref) can recover work after process/home loss."""
    explicit = getattr(provider, "durable_job_reconciliation", None)
    if explicit is not None:
        return bool(explicit)
    provider_id = str(getattr(provider, "provider_id", "") or "")
    if provider_id in {"mock", "loopback"}:
        return True
    return False


def ledger_provider_inflight_op_id(parent_op_id: str, node_id: str) -> str:
    return f"{parent_op_id}:provider_inflight:{node_id}"


def load_ledger_provider_inflight_row(
    journal: Any, parent_op_id: str | None, node_id: str
) -> dict[str, Any] | None:
    if journal is None or not parent_op_id:
        return None
    op_id = ledger_provider_inflight_op_id(parent_op_id, node_id)
    row = journal.get_operation(op_id)
    return cast(dict[str, Any], row) if row is not None else None


def load_ledger_provider_inflight(
    journal: Any, parent_op_id: str | None, node_id: str
) -> dict[str, Any] | None:
    row = load_ledger_provider_inflight_row(journal, parent_op_id, node_id)
    if row is None or str(row.get("status") or "") != "committed":
        return None
    payload = json.loads(row.get("payload_json") or "{}")
    ref = str(payload.get("provider_job_ref") or "")
    if not ref:
        return None
    return cast(dict[str, Any], payload)


def provider_inflight_pending_without_ref(
    journal: Any, parent_op_id: str | None, node_id: str
) -> dict[str, Any] | None:
    """Prepared submit intent exists but ledger ref was never committed."""
    row = load_ledger_provider_inflight_row(journal, parent_op_id, node_id)
    if row is None or str(row.get("status") or "") != "pending":
        return None
    payload = json.loads(row.get("payload_json") or "{}")
    if str(payload.get("provider_job_ref") or ""):
        return None
    return cast(dict[str, Any], payload)


def reconcile_provider_ref(provider: Any, ref: ProviderJobRef) -> JobStatus | None:
    """Poll vendor status; None when outcome is still unknown (pending)."""
    status = provider.status(ref)
    if status.state in {JobState.QUEUED, JobState.RUNNING, JobState.CREATED}:
        return None
    if status.state == JobState.FAILED and status.error and status.error.code == ErrorCode.UNKNOWN:
        return None
    return cast(JobStatus, status)
