"""Replay committed journal operations into the engine (post-ack side effects)."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from vinci_storage.durable_journal import DurableJournal, JournalError

from vinci_daemon.durable_receipts import try_resume_pending_run_output
from vinci_daemon.ledger_replay import (
    _applied,
    adapt_run_replay_complete,
    apply_committed_operation,
    has_run_output_receipt,
    rebuild_acknowledged_metadata,
)

LOG = logging.getLogger("vinci.outbox_dispatch")


class DispatchPendingError(RuntimeError):
    """Outbox row must remain pending (retry later)."""


_EXEC_KINDS = frozenset(
    {"run_accept", "run_approve", "adapt_run", "adapt_batch", "mcp_rpc"}
)


def reconcile_pending_outbox(journal: DurableJournal, engine: Any) -> int:
    import time

    from vinci_daemon.journal_fencing import assert_journal_writer_live, writer_is_fenced

    if writer_is_fenced(engine):
        raise JournalError("journal writer fenced before outbox reconcile")
    assert_journal_writer_live(journal, engine)
    rebuild_acknowledged_metadata(journal, engine)
    delay_ms = os.environ.get("VINCI_TEST_SLEEP_DURING_STARTUP_OUTBOX_MS")
    if delay_ms:
        time.sleep(int(delay_ms) / 1000.0)
        if writer_is_fenced(engine):
            raise JournalError("journal writer fenced during startup outbox")
        assert_journal_writer_live(journal, engine)
    count = 0
    for row in journal.list_pending_outbox():
        op_id = str(row["op_id"])
        if op_id.endswith(":output"):
            journal.mark_outbox_dispatched(op_id)
            continue
        try:
            if dispatch_committed_operation(journal, engine, op_id):
                count += 1
        except DispatchPendingError:
            LOG.warning("outbox pending retry op=%s", op_id)
        except JournalError:
            from vinci_daemon.journal_fencing import fence_journal_writer

            fence_journal_writer(engine)
            LOG.warning("outbox dispatch fenced writer op=%s", op_id)
            break
        except Exception:
            LOG.exception("outbox dispatch failed for %s", op_id)
    return count


def dispatch_committed_operation(
    journal: DurableJournal, engine: Any, op_id: str
) -> bool:
    from vinci_daemon.journal_fencing import assert_journal_writer_live, writer_is_fenced

    if writer_is_fenced(engine):
        raise JournalError("journal writer fenced during outbox dispatch")
    assert_journal_writer_live(journal, engine)
    op = journal.get_operation(op_id)
    if op is None or op.get("status") != "committed":
        return False
    kind = str(op.get("kind") or "")
    if op_id not in _applied(engine):
        apply_committed_operation(engine, op)
        _applied(engine).add(op_id)

    if kind not in _EXEC_KINDS:
        journal.mark_outbox_dispatched(op_id)
        return True

    payload = json.loads(op.get("payload_json") or "{}")
    response = json.loads(op.get("response_json") or "{}")

    if kind == "run_accept":
        return _dispatch_run_accept(journal, engine, op_id, payload, response)
    if kind == "run_approve":
        return _dispatch_run_approve(journal, engine, op_id, payload, response)
    if kind in {"adapt_run", "adapt_batch"}:
        return _dispatch_adapt(journal, engine, op_id, kind, payload, response)
    if kind == "mcp_rpc":
        return _dispatch_mcp_rpc(journal, engine, op_id, payload, response)
    raise DispatchPendingError(f"unhandled exec kind {kind}")


def _terminal_run_may_dispatch(
    journal: DurableJournal, op_id: str, run_id: str, state: str
) -> bool:
    if state in {"completed", "cancelled", "awaiting_approval"}:
        if state == "completed" and not has_run_output_receipt(journal, op_id):
            raise DispatchPendingError(
                f"run {run_id} completed locally without durable output receipt"
            )
        return True
    if state == "failed":
        if has_run_output_receipt(journal, op_id):
            return True
        raise DispatchPendingError(f"run {run_id} failed without durable output receipt")
    return False


def _maybe_resume_run_output(journal: DurableJournal, engine: Any, op_id: str) -> None:
    token = getattr(engine, "_journal_token", None)
    if token is not None:
        try_resume_pending_run_output(journal, token, engine, op_id)


def _dispatch_run_accept(
    journal: DurableJournal,
    engine: Any,
    op_id: str,
    payload: dict[str, Any],
    response: dict[str, Any],
) -> bool:
    _maybe_resume_run_output(journal, engine, op_id)
    if has_run_output_receipt(journal, op_id):
        journal.mark_outbox_dispatched(op_id)
        return True
    run_id = str(response.get("id") or response.get("run_id") or "")
    if not run_id:
        raise DispatchPendingError("run_accept missing run id in ledger response")
    run = engine.store.get_run(run_id)
    if run is None:
        raise DispatchPendingError(f"run {run_id} not materialized from ledger")
    state = str(run.get("state") or "")
    if _terminal_run_may_dispatch(journal, op_id, run_id, state):
        journal.mark_outbox_dispatched(op_id)
        return True
    if state not in {"queued", "running"}:
        raise DispatchPendingError(f"run {run_id} unexpected state {state}")
    finished = engine.dispatch_run(run_id, operation_id=op_id, receipt_parent_op_id=op_id)
    state = str(finished.get("state") or "")
    if state == "failed" and not has_run_output_receipt(journal, op_id):
        raise DispatchPendingError(f"run {run_id} failed without durable output receipt")
    if state not in {"completed", "failed"}:
        raise DispatchPendingError(f"run {run_id} not terminal after dispatch")
    if state == "completed" and not has_run_output_receipt(journal, op_id):
        raise DispatchPendingError(f"run {run_id} completed without durable output receipt")
    journal.mark_outbox_dispatched(op_id)
    return True


def _dispatch_run_approve(
    journal: DurableJournal,
    engine: Any,
    op_id: str,
    payload: dict[str, Any],
    response: dict[str, Any],
) -> bool:
    run_id = str(payload.get("run_id") or response.get("id") or "")
    if not run_id:
        raise DispatchPendingError("run_approve missing run_id")
    run = engine.store.get_run(run_id)
    if run is None:
        raise DispatchPendingError(f"run {run_id} not materialized from ledger")
    if has_run_output_receipt(journal, op_id):
        journal.mark_outbox_dispatched(op_id)
        return True
    state = str(run.get("state") or "")
    if _terminal_run_may_dispatch(journal, op_id, run_id, state):
        journal.mark_outbox_dispatched(op_id)
        return True
    finished = engine.dispatch_run(run_id, operation_id=op_id, receipt_parent_op_id=op_id)
    if str(finished.get("state") or "") not in {"completed", "failed"}:
        raise DispatchPendingError(f"run {run_id} not terminal after approve dispatch")
    if not has_run_output_receipt(journal, op_id):
        raise DispatchPendingError(f"run {run_id} missing durable output receipt after dispatch")
    journal.mark_outbox_dispatched(op_id)
    return True


def _dispatch_adapt(
    journal: DurableJournal,
    engine: Any,
    op_id: str,
    kind: str,
    payload: dict[str, Any],
    response: dict[str, Any],
) -> bool:
    if not response:
        raise DispatchPendingError(f"{kind} missing committed response")
    if kind == "adapt_run":
        if not adapt_run_replay_complete(engine, response):
            raise DispatchPendingError("adapt_run ledger not fully materialized (cas/assets)")
        journal.mark_outbox_dispatched(op_id)
        return True
    if kind == "adapt_batch":
        from vinci_daemon.ledger_batch import ensure_adapt_batch_outbox_complete

        try:
            ensure_adapt_batch_outbox_complete(journal, engine, op_id, response)
        except Exception as exc:
            raise DispatchPendingError(str(exc)) from exc
        if os.environ.get("VINCI_TEST_EXIT_BEFORE_OUTBOX_DONE") == "1":
            os._exit(137)  # noqa: SLF001
        journal.mark_outbox_dispatched(op_id)
        return True
    raise DispatchPendingError(f"unknown adapt kind {kind}")


def _finish_mcp_deferred_outbox(
    journal: DurableJournal,
    engine: Any,
    op_id: str,
    payload: dict[str, Any],
    response: dict[str, Any],
) -> bool:
    from vinci_daemon.ledger_child_commit import child_bundle_committed
    from vinci_daemon.ledger_mcp import commit_mcp_terminal_bundle

    token = getattr(engine, "_journal_token", None)
    if token is None:
        raise DispatchPendingError("mcp_rpc missing journal writer token")
    if not child_bundle_committed(journal, op_id, "mcp_bundle"):
        commit_mcp_terminal_bundle(journal, token, engine, op_id, payload, response)
    if not child_bundle_committed(journal, op_id, "mcp_bundle"):
        raise DispatchPendingError(f"mcp_rpc {op_id} missing committed mcp_bundle")
    if os.environ.get("VINCI_TEST_EXIT_BEFORE_OUTBOX_DONE") == "1":
        os._exit(137)  # noqa: SLF001
    journal.mark_outbox_dispatched(op_id)
    return True


def _dispatch_mcp_rpc(
    journal: DurableJournal,
    engine: Any,
    op_id: str,
    payload: dict[str, Any],
    response: dict[str, Any],
) -> bool:
    from vinci_mcp.server import _DEFERRED_EXEC_TOOLS

    tool = str(payload.get("tool") or "")
    if tool not in _DEFERRED_EXEC_TOOLS:
        journal.mark_outbox_dispatched(op_id)
        return True
    if response.get("error"):
        journal.mark_outbox_dispatched(op_id)
        return True
    result = response.get("result") or {}
    content = result.get("content") or []
    if not content or not isinstance(content[0], dict):
        raise DispatchPendingError("mcp_rpc missing tools/call result")
    text = content[0].get("text")
    if not text:
        raise DispatchPendingError("mcp_rpc missing result text")
    data = json.loads(text)
    if tool == "vinci.adapts_run":
        batch_id = str(data.get("batch_id") or "")
        if not batch_id:
            raise DispatchPendingError("mcp adapts_run missing batch_id")
        parent = dict(response.get("ledger_batch_intent") or {})
        if not parent.get("batch_file"):
            parent = {"batch_id": batch_id, **parent}
        parent["batch_id"] = batch_id
        return _dispatch_adapt(
            journal,
            engine,
            op_id,
            "adapt_batch",
            {"batch_id": batch_id},
            parent,
        )
    run_id = str(data.get("id") or "")
    if not run_id:
        raise DispatchPendingError("mcp run tool missing run id")
    _maybe_resume_run_output(journal, engine, op_id)
    if has_run_output_receipt(journal, op_id):
        return _finish_mcp_deferred_outbox(journal, engine, op_id, payload, response)
    run = engine.store.get_run(run_id)
    if run is None:
        raise DispatchPendingError(f"mcp run {run_id} not materialized")
    state = str(run.get("state") or "")
    if _terminal_run_may_dispatch(journal, op_id, run_id, state):
        return _finish_mcp_deferred_outbox(journal, engine, op_id, payload, response)
    if state not in {"queued", "running"}:
        raise DispatchPendingError(f"mcp run {run_id} unexpected state {state}")
    engine.dispatch_run(run_id, operation_id=op_id, receipt_parent_op_id=op_id)
    run = engine.store.get_run(run_id) or run
    state = str(run.get("state") or "")
    if state == "failed" and not has_run_output_receipt(journal, op_id):
        raise DispatchPendingError(f"mcp run {run_id} failed without output receipt")
    if state == "completed" and not has_run_output_receipt(journal, op_id):
        raise DispatchPendingError(f"mcp run {run_id} completed without output receipt")
    if state not in {"completed", "failed"}:
        raise DispatchPendingError(f"mcp run {run_id} not terminal after dispatch")
    return _finish_mcp_deferred_outbox(journal, engine, op_id, payload, response)
