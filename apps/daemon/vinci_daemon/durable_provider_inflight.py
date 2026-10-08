"""Durable ledger child for provider submit refs (survives VINCI_HOME wipe)."""

from __future__ import annotations

import logging
from typing import Any

from vinci_runtime.provider_reconciliation import ledger_provider_inflight_op_id
from vinci_storage.durable_journal import DurableJournal, JournalError

from vinci_daemon.journal_fencing import require_live_writer, writer_is_fenced
from vinci_daemon.ledger_child_commit import commit_child_operation

LOG = logging.getLogger("vinci.durable_provider_inflight")


def prepare_provider_submit_intent(
    journal: DurableJournal,
    engine: Any,
    *,
    parent_op_id: str,
    run_id: str,
    node_id: str,
    job_id: str,
    model_id: str,
    provider_name: str,
    idempotency_key: str,
) -> None:
    """Durable intent before external provider.submit (fail-closed gap if never committed)."""
    if writer_is_fenced(engine):
        raise JournalError("journal writer fenced")
    token = require_live_writer(engine)
    op_id = ledger_provider_inflight_op_id(parent_op_id, node_id)
    existing = journal.get_operation(op_id)
    if existing is not None:
        status = str(existing.get("status") or "")
        if status in {"pending", "committed"}:
            return
    payload = {
        "run_id": run_id,
        "node_id": node_id,
        "job_id": job_id,
        "model_id": model_id,
        "provider": provider_name,
        "provider_job_ref": "",
        "idempotency_key": idempotency_key,
        "submit_intent": True,
    }
    journal.prepare_operation(
        token,
        op_id=op_id,
        kind="provider_inflight",
        path=f"/runs/{run_id}/nodes/{node_id}/provider_inflight",
        blob_keys=[],
        payload=payload,
    )
    LOG.debug("prepared provider_inflight intent op=%s job=%s", op_id, job_id)


def commit_provider_inflight(
    journal: DurableJournal,
    engine: Any,
    *,
    parent_op_id: str,
    run_id: str,
    node_id: str,
    job_id: str,
    model_id: str,
    provider_name: str,
    provider_job_ref: str,
    idempotency_key: str,
) -> None:
    if writer_is_fenced(engine):
        raise JournalError("journal writer fenced")
    token = require_live_writer(engine)
    op_id = ledger_provider_inflight_op_id(parent_op_id, node_id)
    payload = {
        "run_id": run_id,
        "node_id": node_id,
        "job_id": job_id,
        "model_id": model_id,
        "provider": provider_name,
        "provider_job_ref": provider_job_ref,
        "idempotency_key": idempotency_key,
    }
    response = dict(payload)
    existing = journal.get_operation(op_id)
    if existing is not None and str(existing.get("status") or "") == "committed":
        return
    commit_child_operation(
        journal,
        token,
        op_id=op_id,
        kind="provider_inflight",
        path=f"/runs/{run_id}/nodes/{node_id}/provider_inflight",
        blob_keys=[],
        payload=payload,
        response=response,
    )
    LOG.debug("committed provider_inflight op=%s ref=%s", op_id, provider_job_ref)
