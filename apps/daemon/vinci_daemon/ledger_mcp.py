"""MCP JSON-RPC envelope durable commit + replay side effects."""

from __future__ import annotations

import json
from typing import Any

from vinci_mcp.server import _DEFERRED_EXEC_TOOLS, MUTATING_TOOLS
from vinci_storage.durable_journal import CommitResult, DurableJournal, JournalError

from vinci_daemon.ledger_child_commit import commit_child_operation


def mcp_tool_deferred(ledger_payload: dict[str, Any]) -> bool:
    if ledger_payload.get("method") != "tools/call":
        return False
    tool = str(ledger_payload.get("tool") or "")
    return tool in _DEFERRED_EXEC_TOOLS


def attach_mcp_portable(
    engine: Any, ledger_payload: dict[str, Any], envelope: dict[str, Any]
) -> dict[str, Any]:
    """Require jsonrpc envelope; embed ledger_replay for mutating tools/call (immediate tools)."""
    if not envelope.get("jsonrpc"):
        raise JournalError("mcp_rpc response must be a JSON-RPC envelope")
    out = dict(envelope)
    if ledger_payload.get("method") != "tools/call":
        return out
    tool = str(ledger_payload.get("tool") or "")
    if tool not in MUTATING_TOOLS or tool in _DEFERRED_EXEC_TOOLS:
        return out
    if envelope.get("error"):
        return out
    result = envelope.get("result") or {}
    content = result.get("content") or []
    if not content or not isinstance(content[0], dict):
        raise JournalError("mcp tools/call missing result content")
    text = content[0].get("text")
    if not text:
        raise JournalError("mcp tools/call missing result text")
    data = json.loads(text)
    replay = _replay_bundle_for_tool(engine, tool, data)
    out["ledger_replay"] = replay
    return out


def _replay_bundle_for_tool(engine: Any, tool: str, data: dict[str, Any]) -> dict[str, Any]:
    if tool in {"vinci.image_generate", "vinci.video_generate", "vinci.workflow_run"}:
        return _run_tool_bundle(engine, data)
    if tool == "vinci.adapts_run":
        batch_id = data.get("batch_id")
        if not batch_id:
            raise JournalError("mcp adapts_run missing batch_id")
        from vinci_daemon.ledger_batch import capture_adapt_batch_bundle

        return capture_adapt_batch_bundle(engine, str(batch_id))
    if tool == "vinci.jobs_cancel":
        run_id = str(data.get("id") or data.get("run_id") or "")
        if not run_id:
            raise JournalError("mcp jobs_cancel missing run id in response")
        run = engine.store.get_run(run_id)
        if run is None:
            raise JournalError(f"mcp jobs_cancel run missing from store: {run_id}")
        return {"kind": "run_cancel", "run": dict(run)}
    raise JournalError(f"unsupported mutating mcp tool {tool}")


def _run_tool_bundle(engine: Any, run_body: dict[str, Any]) -> dict[str, Any]:
    run_id = str(run_body.get("id") or "")
    if not run_id:
        raise JournalError("mcp run tool missing run id")
    outputs = [str(x) for x in (run_body.get("outputs") or []) if x]
    jobs: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    assets: list[dict[str, Any]] = []
    for jid in run_body.get("job_ids") or []:
        job = engine.store.get_job(str(jid))
        if job is None:
            raise JournalError(f"mcp run missing job {jid}")
        jobs.append(job.model_dump(mode="json"))
        if job.receipt is not None:
            receipts.append(job.receipt.model_dump(mode="json"))
    for digest in outputs:
        asset = engine.store.get_asset(str(digest))
        if asset is None:
            raise JournalError(f"mcp run missing asset metadata {digest}")
        if not engine.cas.exists(str(digest)):
            raise JournalError(f"mcp run missing cas blob {digest}")
        assets.append(asset.model_dump(mode="json"))
    return {
        "kind": "run",
        "run": run_body,
        "outputs": outputs,
        "jobs": jobs,
        "receipts": receipts,
        "assets": assets,
    }


def commit_mcp_terminal_bundle(
    journal: DurableJournal,
    token: CommitResult,
    engine: Any,
    parent_op_id: str,
    ledger_payload: dict[str, Any],
    envelope: dict[str, Any],
) -> dict[str, Any]:
    """After outbox dispatch: persist terminal ledger_replay + refresh MCP result text."""
    tool = str(ledger_payload.get("tool") or "")
    if tool not in _DEFERRED_EXEC_TOOLS:
        return envelope
    if envelope.get("error"):
        return envelope
    result = envelope.get("result") or {}
    content = result.get("content") or []
    if not content or not isinstance(content[0], dict):
        raise JournalError("mcp deferred tool missing result content")
    text = content[0].get("text")
    if not text:
        raise JournalError("mcp deferred tool missing result text")
    data = json.loads(text)
    data = _fresh_tool_result(engine, tool, data)
    replay = _replay_bundle_for_tool(engine, tool, data)
    bundle_op = f"{parent_op_id}:mcp_bundle"
    payload = {"parent_op_id": parent_op_id, "tool": tool}
    commit_child_operation(
        journal,
        token,
        op_id=bundle_op,
        kind="mcp_rpc_bundle",
        path="/mcp/bundle",
        payload=payload,
        blob_keys=[],
        response=replay,
        exit_after_prepare_env="VINCI_TEST_EXIT_AFTER_BUNDLE_PREPARE",
    )
    return _envelope_with_replay(envelope, replay, data)


def enrich_mcp_adapt_batch_intent(
    engine: Any, ledger_payload: dict[str, Any], envelope: dict[str, Any]
) -> dict[str, Any]:
    if str(ledger_payload.get("tool") or "") != "vinci.adapts_run":
        return envelope
    out = dict(envelope)
    result = out.get("result") or {}
    content = result.get("content") or []
    if not content or not isinstance(content[0], dict) or not content[0].get("text"):
        return out
    data = json.loads(content[0]["text"])
    batch_id = str(data.get("batch_id") or "")
    if not batch_id:
        return out
    from vinci_daemon.ledger_batch import adapt_batch_parent_snapshot

    out["ledger_batch_intent"] = adapt_batch_parent_snapshot(engine, batch_id)
    return out


def refresh_mcp_envelope_from_journal(
    journal: DurableJournal,
    engine: Any,
    parent_op_id: str,
    ledger_payload: dict[str, Any],
    envelope: dict[str, Any],
) -> dict[str, Any]:
    replay = replay_bundle_for_op(journal, parent_op_id, envelope)
    if replay is None:
        return envelope
    tool = str(ledger_payload.get("tool") or "")
    data = json.loads(
        (envelope.get("result") or {}).get("content", [{}])[0].get("text") or "{}"
    )
    data = _fresh_tool_result(engine, tool, data)
    return _envelope_with_replay(envelope, replay, data)


def _fresh_tool_result(engine: Any, tool: str, data: dict[str, Any]) -> dict[str, Any]:
    if tool in {"vinci.image_generate", "vinci.video_generate", "vinci.workflow_run"}:
        run_id = str(data.get("id") or "")
        if run_id:
            fresh = engine.store.get_run(run_id)
            if fresh is not None:
                return fresh
    if tool == "vinci.adapts_run":
        batch_id = str(data.get("batch_id") or "")
        if batch_id:
            try:
                return engine.adapt_batch_status(batch_id)
            except KeyError:
                return data
    return data


def _envelope_with_replay(
    envelope: dict[str, Any], replay: dict[str, Any], data: dict[str, Any]
) -> dict[str, Any]:
    out = dict(envelope)
    out["ledger_replay"] = replay
    result = dict(out.get("result") or {})
    content = list(result.get("content") or [])
    if content and isinstance(content[0], dict):
        content[0] = {**content[0], "text": json.dumps(data, default=str)}
        result["content"] = content
    out["result"] = result
    return out


def replay_bundle_for_op(
    journal: DurableJournal, parent_op_id: str, envelope: dict[str, Any]
) -> dict[str, Any] | None:
    bundled = envelope.get("ledger_replay")
    if isinstance(bundled, dict):
        return bundled
    for suffix in ("mcp_bundle", "batch_bundle"):
        row = journal.get_operation(f"{parent_op_id}:{suffix}")
        if row is None or row.get("status") != "committed":
            continue
        stored = json.loads(row.get("response_json") or "{}")
        if stored:
            return stored
    return None


def replay_mcp_envelope(
    engine: Any,
    envelope: dict[str, Any],
    ledger_payload: dict[str, Any],
    journal: DurableJournal | None = None,
    parent_op_id: str | None = None,
) -> None:
    if ledger_payload.get("method") != "tools/call":
        return
    tool = str(ledger_payload.get("tool") or "")
    if tool not in MUTATING_TOOLS:
        return
    if envelope.get("error"):
        return
    replay = envelope.get("ledger_replay")
    if not isinstance(replay, dict) and journal is not None and parent_op_id:
        replay = replay_bundle_for_op(journal, parent_op_id, envelope)
    if not isinstance(replay, dict):
        raise RuntimeError("mcp_rpc missing ledger_replay portable bundle")
    from vinci_daemon.ledger_batch import restore_adapt_batch_bundle
    from vinci_daemon.ledger_replay import (
        _materialize_run,
        _materialize_run_output,
    )

    kind = replay.get("kind")
    if kind == "run":
        run_body = replay.get("run") or {}
        _materialize_run(engine, run_body)
        _materialize_run_output(
            engine,
            {**replay, "run_id": run_body.get("id")},
            replay.get("outputs") or [],
        )
    elif kind == "adapt_batch":
        restore_adapt_batch_bundle(engine, replay)
    elif kind == "run_cancel":
        run_body = replay.get("run") or {}
        if run_body.get("id"):
            _materialize_run(engine, {**run_body, "state": "cancelled"})
    else:
        raise RuntimeError(f"unknown mcp ledger_replay kind {kind}")
