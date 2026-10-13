"""Durable run output + receipt commits (before local completed state)."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from vinci_storage.durable_journal import CommitResult, DurableJournal, JournalError
from vinci_storage.journal_payload import payload_digest

from vinci_daemon.journal_fencing import require_live_writer, writer_is_fenced
from vinci_daemon.ledger_child_commit import commit_child_operation

LOG = logging.getLogger("vinci.durable_receipts")


def _output_payload(
    run_id: str, state: str, outputs: list[str], response: dict[str, Any]
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "state": state,
        "outputs": outputs,
        "terminal": response,
    }


def try_resume_pending_run_output(
    journal: DurableJournal,
    token: CommitResult,
    engine: Any,
    parent_op_id: str,
) -> bool:
    """Finish a prepared :output row without re-executing the workflow."""
    receipt_op = f"{parent_op_id}:output"
    row = journal.get_operation(receipt_op)
    if row is None or str(row.get("status") or "") != "pending":
        return False
    payload = json.loads(row.get("payload_json") or "{}")
    terminal = payload.get("terminal")
    if not isinstance(terminal, dict):
        return False
    outputs = [str(x) for x in (terminal.get("outputs") or payload.get("outputs") or []) if x]
    for key in outputs:
        if not engine.cas.exists(key):
            return False
    run_id = str(terminal.get("run_id") or payload.get("run_id") or "")
    if not run_id:
        return False
    commit_child_operation(
        journal,
        token,
        op_id=receipt_op,
        kind="run_output",
        path=f"/runs/{run_id}/output",
        blob_keys=outputs,
        payload=payload,
        response=terminal,
    )
    from vinci_daemon.ledger_replay import apply_committed_operation

    committed = journal.get_operation(receipt_op)
    if committed is not None and committed.get("status") == "committed":
        apply_committed_operation(engine, committed)
        return True
    return False


def commit_run_receipt_before_complete(
    journal: DurableJournal,
    engine: Any,
    *,
    parent_op_id: str,
    run_id: str,
    run_body: dict[str, Any],
) -> None:
    """Persist output blob keys + receipt URIs to ledger; raises on failure."""
    if writer_is_fenced(engine):
        raise JournalError("journal writer fenced")
    token = require_live_writer(engine)
    outputs = [str(x) for x in (run_body.get("outputs") or []) if x]
    state = "completed" if outputs else str(run_body.get("state") or "completed")
    receipt_op = f"{parent_op_id}:output"
    for key in outputs:
        if not engine.cas.exists(key):
            raise JournalError(f"output blob missing in cas: {key}")
    jobs: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    assets: list[dict[str, Any]] = []
    for jid in run_body.get("job_ids") or []:
        job = engine.store.get_job(str(jid))
        if job is None:
            raise JournalError(f"job missing for durable receipt: {jid}")
        jobs.append(job.model_dump(mode="json"))
        if job.receipt is not None:
            receipts.append(job.receipt.model_dump(mode="json"))
    for digest in outputs:
        asset = engine.store.get_asset(str(digest))
        if asset is None:
            raise JournalError(f"output asset metadata missing for {digest}")
        assets.append(asset.model_dump(mode="json"))
    response = {
        "run_id": run_id,
        "state": state,
        "outputs": outputs,
        "job_ids": run_body.get("job_ids") or [],
        "job_uris": run_body.get("job_uris") or [],
        "asset_uris": run_body.get("asset_uris") or [],
        "receipt_uris": run_body.get("receipt_uris") or [],
        "jobs": jobs,
        "receipts": receipts,
        "assets": assets,
    }
    payload = _output_payload(run_id, state, outputs, response)
    digest = payload_digest(payload)
    existing = journal.get_operation(receipt_op)
    if existing is not None:
        if existing.get("payload_digest") != digest:
            raise JournalError("run output receipt payload conflict")
        if str(existing.get("status") or "") == "committed":
            return
    if os.environ.get("VINCI_TEST_EXIT_BEFORE_OUTPUT_COMMIT") == "1":
        os._exit(137)  # noqa: SLF001 — kill before run_output ledger prepare
    commit_child_operation(
        journal,
        token,
        op_id=receipt_op,
        kind="run_output",
        path=f"/runs/{run_id}/output",
        blob_keys=outputs,
        payload=payload,
        response=response,
        exit_after_prepare_env="VINCI_TEST_EXIT_AFTER_OUTPUT_PREPARE",
    )
    from vinci_daemon.ledger_replay import apply_committed_operation

    row = journal.get_operation(receipt_op)
    if row is not None and row.get("status") == "committed":
        apply_committed_operation(engine, row)
