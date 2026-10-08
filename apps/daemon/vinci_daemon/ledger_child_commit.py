"""Resume prepared child ledger rows (bundle commits after crash)."""

from __future__ import annotations

import json
import os
from typing import Any

from vinci_storage.durable_journal import CommitResult, DurableJournal


def _record_ledger_commit() -> None:
    try:
        from vinci_runtime.writer_effect_trace import record_writer_effect

        record_writer_effect("ledger_commit")
    except ImportError:
        return


def _response_nonempty(response: dict[str, Any]) -> bool:
    if not response:
        return False
    if response.get("kind") == "adapt_batch":
        return bool(response.get("batch_file") and response.get("batch_status"))
    if response.get("kind") in {"run", "adapt_batch", "run_cancel"}:
        return True
    return bool(response)


def commit_child_operation(
    journal: DurableJournal,
    token: CommitResult,
    *,
    op_id: str,
    kind: str,
    path: str,
    payload: dict[str, Any],
    blob_keys: list[str],
    response: dict[str, Any],
    exit_after_prepare_env: str | None = None,
) -> dict[str, Any]:
    """Prepare+commit or resume a pending child row; never treat pending as done."""
    existing = journal.get_operation(op_id)
    if existing is not None:
        status = str(existing.get("status") or "")
        if status == "committed":
            stored = json.loads(existing.get("response_json") or "{}")
            if _response_nonempty(stored):
                return stored
        if status == "pending":
            if exit_after_prepare_env and os.environ.get(exit_after_prepare_env) == "1":
                os._exit(137)  # noqa: SLF001
            journal.commit_ack(
                token,
                kind=kind,
                path=path,
                blob_keys=blob_keys,
                payload=payload,
                response=response,
                op_id=op_id,
            )
            _record_ledger_commit()
            return response
    journal.prepare_operation(
        token,
        op_id=op_id,
        kind=kind,
        path=path,
        blob_keys=blob_keys,
        payload=payload,
    )
    if exit_after_prepare_env and os.environ.get(exit_after_prepare_env) == "1":
        os._exit(137)  # noqa: SLF001
    journal.commit_ack(
        token,
        kind=kind,
        path=path,
        blob_keys=blob_keys,
        payload=payload,
        response=response,
        op_id=op_id,
    )
    _record_ledger_commit()
    return response


def child_bundle_committed(journal: DurableJournal, parent_op_id: str, suffix: str) -> bool:
    row = journal.get_operation(f"{parent_op_id}:{suffix}")
    if row is None or row.get("status") != "committed":
        return False
    stored = json.loads(row.get("response_json") or "{}")
    return _response_nonempty(stored)
