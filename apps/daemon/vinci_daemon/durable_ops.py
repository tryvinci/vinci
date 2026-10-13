"""Durable-before-ack helpers for daemon mutation handlers."""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable
from typing import Any, TypeVar

from fastapi import HTTPException
from starlette.requests import Request
from vinci_storage.durable_journal import CommitResult, DurableJournal, JournalError
from vinci_storage.durable_paths import JOURNAL_WIRED_KINDS, classify_mutation
from vinci_storage.journal_payload import commit_blob_keys

from vinci_daemon.journal_fencing import require_live_writer, writer_is_fenced
from vinci_daemon.ledger_batch import enrich_adapt_batch_response
from vinci_daemon.ledger_mcp import (
    attach_mcp_portable,
    enrich_mcp_adapt_batch_intent,
    mcp_tool_deferred,
    refresh_mcp_envelope_from_journal,
)
from vinci_daemon.ledger_portable import PORTABLE_REQUIRED_KINDS, attach_portable_snapshot
from vinci_daemon.outbox_dispatch import dispatch_committed_operation

T = TypeVar("T")


def require_journal_wired(method: str, path: str) -> str:
    kind = classify_mutation(method, path)
    if kind is None:
        raise HTTPException(status_code=405, detail="not a mutation")
    if kind not in JOURNAL_WIRED_KINDS:
        raise HTTPException(
            status_code=501,
            detail=f"journal_not_wired:{kind}",
        )
    return kind


def client_operation_id(request: Request) -> str:
    raw = request.headers.get("x-vinci-operation-id", "").strip()
    if raw:
        return raw
    return str(uuid.uuid4())


def durable_response(
    journal: DurableJournal,
    token: CommitResult,
    *,
    kind: str,
    path: str,
    payload: dict[str, Any],
    blob_keys: list[str],
    op_id: str,
    build_response: Callable[[], dict[str, Any]],
    engine: Any,
) -> dict[str, Any]:
    """Intent already recorded; run handler then commit before returning."""
    if writer_is_fenced(engine):
        raise HTTPException(status_code=503, detail="journal_writer_fenced")
    token = require_live_writer(engine)
    journal.renew_writer(token)
    prepared = journal.prepare_operation(
        token,
        op_id=op_id,
        kind=kind,
        path=path,
        blob_keys=blob_keys,
        payload=payload,
    )
    if prepared.cached_response is not None:
        return prepared.cached_response
    response = build_response()
    if kind == "adapt_batch":
        response = enrich_adapt_batch_response(engine, response)
    if kind in PORTABLE_REQUIRED_KINDS:
        response = attach_portable_snapshot(kind, engine, payload, response)
    if kind == "mcp_rpc" and not mcp_tool_deferred(payload):
        response = attach_mcp_portable(engine, payload, response)
    if kind == "mcp_rpc" and mcp_tool_deferred(payload):
        response = enrich_mcp_adapt_batch_intent(engine, payload, response)
    if os.environ.get("VINCI_TEST_EXIT_BEFORE_COMMIT") == "1":
        os._exit(137)  # noqa: SLF001 — subprocess kill-point tests only
    ack_blobs = commit_blob_keys(kind, blob_keys, response)
    try:
        journal.commit_ack(
            token,
            kind=kind,
            path=path,
            blob_keys=ack_blobs,
            payload=payload,
            response=response,
            op_id=op_id,
        )
        try:
            from vinci_runtime.writer_effect_trace import record_writer_effect

            record_writer_effect("ledger_ack")
        except ImportError:
            pass
    except JournalError as exc:
        raise HTTPException(status_code=503, detail=f"journal_commit_failed:{exc}") from exc
    if os.environ.get("VINCI_TEST_EXIT_AFTER_ACK") == "1":
        os._exit(137)  # noqa: SLF001 — kill after ack, before outbox dispatch
    response.setdefault("operation_id", op_id)
    dispatch_committed_operation(journal, engine, op_id)
    if kind == "mcp_rpc" and mcp_tool_deferred(payload):
        response = refresh_mcp_envelope_from_journal(
            journal, engine, op_id, payload, response
        )
        from vinci_daemon.ledger_mcp import replay_mcp_envelope

        replay_mcp_envelope(
            engine, response, payload, journal=journal, parent_op_id=op_id
        )
    return response


def with_journal_ack(
    request: Request,
    *,
    method: str,
    path: str,
    payload: dict[str, Any],
    blob_keys: list[str],
    build_response: Callable[[], dict[str, Any]],
    operation_id: str | None = None,
) -> dict[str, Any]:
    journal: DurableJournal | None = getattr(request.app.state, "journal", None)
    token: CommitResult | None = getattr(request.app.state, "journal_token", None)
    engine = request.app.state.engine
    if journal is None or token is None:
        return build_response()
    kind = require_journal_wired(method, path)
    op_id = operation_id or client_operation_id(request)
    return durable_response(
        journal,
        token,
        kind=kind,
        path=path,
        payload=payload,
        blob_keys=blob_keys,
        op_id=op_id,
        build_response=build_response,
        engine=engine,
    )
