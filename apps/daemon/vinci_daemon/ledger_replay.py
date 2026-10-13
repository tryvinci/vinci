"""Rebuild local metadata cache from the durable operation ledger (not R2 home snapshots)."""

from __future__ import annotations

import json
import logging
from typing import Any

from vinci_protocol.enums import JobState
from vinci_protocol.models import Asset, Job, JobTimings, Receipt
from vinci_storage.durable_journal import DurableJournal

LOG = logging.getLogger("vinci.ledger_replay")

_APPLIED_ATTR = "_ledger_applied_op_ids"

_RUN_STATE_RANK: dict[str, int] = {
    "queued": 0,
    "running": 1,
    "awaiting_approval": 2,
    "failed": 3,
    "cancelled": 3,
    "completed": 4,
}


def _run_state_rank(state: str) -> int:
    return _RUN_STATE_RANK.get(state, 0)


def _applied(engine: Any) -> set[str]:
    raw = getattr(engine, _APPLIED_ATTR, None)
    if raw is None:
        raw = set()
        setattr(engine, _APPLIED_ATTR, raw)
    return raw


def rebuild_acknowledged_metadata(journal: DurableJournal, engine: Any) -> int:
    """Apply all committed ledger rows in order (dedup by op_id), paginated."""
    count = 0
    for row in journal.iter_committed_operations():
        op_id = str(row.get("op_id") or "")
        if not op_id or op_id in _applied(engine):
            continue
        apply_committed_operation(engine, row)
        _applied(engine).add(op_id)
        count += 1
    return count


def apply_committed_operation(engine: Any, op: dict[str, Any]) -> None:
    kind = str(op.get("kind") or "")
    op_id = str(op.get("op_id") or "")
    response = json.loads(op.get("response_json") or "{}")
    payload = json.loads(op.get("payload_json") or "{}")
    blob_keys = json.loads(op.get("blob_keys_json") or "[]")
    journal = getattr(engine, "_journal", None)

    if kind == "init":
        demo = bool(payload.get("demo") or response.get("demo"))
        if demo and not engine.config.demo:
            engine.init_home(demo=True)
        return

    if kind == "settings":
        kwargs: dict[str, Any] = {}
        for key in (
            "preference",
            "monthly_cap_usd",
            "require_approval_over",
            "gsheet_id",
            "gsheet_tab",
        ):
            if key in response and response[key] is not None:
                kwargs[key] = response[key]
        if kwargs:
            engine.update_settings(**kwargs)
        return

    if kind == "asset_upload":
        _materialize_asset(engine, response, blob_keys)
        return

    if kind == "run_accept":
        _materialize_run(engine, response)
        return

    if kind == "run_approve":
        run_id = str(payload.get("run_id") or response.get("id") or "")
        if run_id:
            run = engine.store.get_run(run_id)
            if run is not None:
                cur = str(run.get("state") or "")
                if _run_state_rank(cur) < _run_state_rank("queued"):
                    engine.store.put_run(run_id, run, "queued")
        return

    if kind == "run_cancel":
        run_id = str(payload.get("run_id") or response.get("id") or "")
        if run_id:
            run = engine.store.get_run(run_id)
            if run is not None:
                run["cancelled"] = True
                engine.store.put_run(run_id, run, "cancelled")
        return

    if kind == "run_output":
        _materialize_run_output(engine, response, blob_keys)
        return

    if kind == "provider_inflight":
        _materialize_provider_inflight(engine, payload)
        return

    if kind in {"preset_create", "preset_delete"}:
        if kind == "preset_create" and response:
            engine.save_custom_preset(response.get("preset") or response)
        elif kind == "preset_delete":
            preset_id = str(
                payload.get("preset_id") or payload.get("id") or response.get("id") or ""
            )
            if preset_id:
                engine.remove_custom_preset(preset_id)
        return

    if kind == "provider_add":
        name = str(payload.get("id") or response.get("id") or "")
        if name:
            engine.add_provider(
                name,
                from_env=payload.get("from_env"),
                secret=payload.get("secret"),
                label=response.get("label"),
                url=payload.get("url"),
                account_id=payload.get("account_id"),
            )
        return

    if kind == "provider_remove":
        name = str(payload.get("name") or payload.get("id") or "")
        if name:
            engine.remove_provider(name)
        return

    if kind == "adapt_run":
        _materialize_adapt_run(engine, response, blob_keys)
        return

    if kind == "adapt_batch":
        if journal is not None:
            bundle_row = journal.get_operation(f"{op_id}:batch_bundle")
            if bundle_row is not None and bundle_row.get("status") == "committed":
                stored = json.loads(bundle_row.get("response_json") or "{}")
                if stored.get("batch_file"):
                    from vinci_daemon.ledger_batch import restore_adapt_batch_bundle

                    restore_adapt_batch_bundle(engine, stored)
                    return
        if response.get("batch_file"):
            from vinci_daemon.ledger_batch import restore_adapt_batch_parent_snapshot

            restore_adapt_batch_parent_snapshot(engine, response, journal, op_id)
            return
        _materialize_adapt_batch(engine, response)
        return

    if kind == "adapt_batch_bundle":
        from vinci_daemon.ledger_batch import restore_adapt_batch_bundle

        restore_adapt_batch_bundle(engine, response)
        return

    if kind == "mcp_rpc_bundle":
        return

    if kind == "skill_install":
        from vinci_daemon.ledger_portable import replay_portable

        replay_portable(engine, kind, response)
        return

    if kind == "comfy_import":
        from vinci_daemon.ledger_portable import replay_comfy

        replay_comfy(engine, response)
        return

    if kind == "gsheet_sync":
        from vinci_daemon.ledger_portable import replay_portable

        replay_portable(engine, kind, response)
        return

    if kind == "catalog_refresh":
        from vinci_daemon.ledger_portable import replay_portable

        replay_portable(engine, kind, response)
        return

    if kind in {"collab_create", "collab_put"}:
        _materialize_collab(engine, response)
        return

    if kind == "mcp_rpc":
        from vinci_daemon.ledger_mcp import (
            mcp_tool_deferred,
            replay_bundle_for_op,
            replay_mcp_envelope,
        )

        bundle = replay_bundle_for_op(journal, op_id, response) if journal else None
        if bundle is not None:
            merged = dict(response)
            merged["ledger_replay"] = bundle
            replay_mcp_envelope(
                engine, merged, payload, journal=journal, parent_op_id=op_id
            )
            return
        if mcp_tool_deferred(payload):
            result = response.get("result") or {}
            content = result.get("content") or []
            if content and isinstance(content[0], dict) and content[0].get("text"):
                import json as _json

                data = _json.loads(content[0]["text"])
                if data.get("batch_id"):
                    intent = response.get("ledger_batch_intent")
                    if isinstance(intent, dict) and intent.get("batch_file"):
                        from vinci_daemon.ledger_batch import (
                            restore_adapt_batch_parent_snapshot,
                        )

                        restore_adapt_batch_parent_snapshot(
                            engine, intent, journal, op_id
                        )
                    return
                if data.get("id"):
                    _materialize_run(engine, data)
            return
        replay_mcp_envelope(
            engine,
            response,
            payload,
            journal=journal,
            parent_op_id=op_id,
        )
        return

    if kind in {
        "provider_oauth",
        "provider_oauth_callback",
        "provider_oauth_disconnect",
        "run_cancel",
    }:
        LOG.debug("ledger apply snapshot kind=%s", kind)
        return

    LOG.debug("ledger apply noop for kind=%s", kind)


def _materialize_asset(engine: Any, response: dict[str, Any], blob_keys: list[str]) -> None:
    asset_id = str(response.get("id") or (blob_keys[0] if blob_keys else ""))
    if not asset_id:
        raise RuntimeError("asset_upload ledger row missing asset id")
    _ensure_asset_record(engine, asset_id, response)


def _ensure_asset_record(engine: Any, digest: str, meta: dict[str, Any] | None = None) -> None:
    if not engine.cas.exists(digest):
        raise RuntimeError(f"cas blob missing for asset {digest}")
    if engine.store.get_asset(digest) is not None:
        return
    if meta and meta.get("id"):
        engine.store.put_asset(Asset.model_validate(meta))
        return
    data = engine.cas.get(digest)
    mime = (meta or {}).get("mime") or "application/octet-stream"
    filename = str((meta or {}).get("metadata", {}).get("filename") or "ledger-replay.bin")
    stored = engine.ingest_bytes(data, mime=mime, filename=filename)
    if stored.id != digest:
        raise RuntimeError(f"cas digest mismatch {stored.id} vs {digest}")


def _materialize_jobs_and_receipts(engine: Any, response: dict[str, Any]) -> None:
    for raw_job in response.get("jobs") or []:
        if not isinstance(raw_job, dict):
            continue
        job = Job.model_validate(raw_job)
        if engine.store.get_job(job.id) is None:
            engine.store.put_job(job)
        for digest in job.outputs:
            _ensure_asset_record(engine, digest, None)
    for raw_receipt in response.get("receipts") or []:
        if not isinstance(raw_receipt, dict):
            continue
        receipt = Receipt.model_validate(raw_receipt)
        if engine.store.get_receipt(receipt.job_id) is None:
            engine.store.put_receipt(receipt)
    for raw_asset in response.get("assets") or []:
        if isinstance(raw_asset, dict) and raw_asset.get("id"):
            _ensure_asset_record(engine, str(raw_asset["id"]), raw_asset)


def _materialize_run(engine: Any, response: dict[str, Any]) -> None:
    run_id = str(response.get("id") or response.get("run_id") or "")
    if not run_id:
        raise RuntimeError("run_accept ledger row missing run id")
    state = str(response.get("state") or "queued")
    body = {k: v for k, v in response.items() if k not in {"id", "state", "created_at"}}
    existing = engine.store.get_run(run_id)
    if existing is not None:
        cur = str(existing.get("state") or "")
        if _run_state_rank(cur) >= _run_state_rank(state):
            state = cur
            for key in (
                "outputs",
                "job_ids",
                "receipt_uris",
                "job_uris",
                "asset_uris",
                "cancelled",
                "nodes",
                "error",
            ):
                if existing.get(key) and not body.get(key):
                    body[key] = existing[key]
        else:
            for key, val in existing.items():
                if key not in body and key not in {"state"}:
                    body[key] = val
    engine.store.put_run(run_id, body, state)


def _materialize_provider_inflight(engine: Any, payload: dict[str, Any]) -> None:
    job_id = str(payload.get("job_id") or "")
    if not job_id or engine.store.get_job(job_id) is not None:
        return
    run_id = str(payload.get("run_id") or "")
    node_id = str(payload.get("node_id") or "")
    ref = str(payload.get("provider_job_ref") or "")
    if not ref:
        return
    job = Job(
        id=job_id,
        workflow_run_id=run_id,
        node_id=node_id,
        model_id=str(payload.get("model_id") or ""),
        provider_job_ref=ref,
        state=JobState.RUNNING,
        inputs={},
        outputs=[],
        timings=JobTimings(),
        idempotency_key=str(payload.get("idempotency_key") or ""),
    )
    engine.store.put_job(job)


def _materialize_run_output(
    engine: Any, response: dict[str, Any], blob_keys: list[str]
) -> None:
    run_id = str(response.get("run_id") or "")
    if not run_id:
        return
    _materialize_jobs_and_receipts(engine, response)
    run = engine.store.get_run(run_id)
    if run is None:
        merged = {"id": run_id, "state": response.get("state", "completed"), **response}
        _materialize_run(engine, merged)
        run = engine.store.get_run(run_id)
    if run is None:
        raise RuntimeError(f"run_output could not materialize run {run_id}")
    outputs = response.get("outputs") or blob_keys
    for digest in outputs:
        meta = next(
            (
                a
                for a in (response.get("assets") or [])
                if isinstance(a, dict) and a.get("id") == digest
            ),
            None,
        )
        _ensure_asset_record(engine, str(digest), meta if isinstance(meta, dict) else None)
    run["outputs"] = outputs
    run["receipt_uris"] = response.get("receipt_uris") or run.get("receipt_uris") or []
    run["job_ids"] = response.get("job_ids") or run.get("job_ids") or []
    if response.get("job_uris"):
        run["job_uris"] = response["job_uris"]
    if response.get("asset_uris"):
        run["asset_uris"] = response["asset_uris"]
    state = str(response.get("state") or "completed")
    if outputs and state == "queued":
        state = "completed"
    cur = str(run.get("state") or "")
    if _run_state_rank(cur) >= _run_state_rank(state):
        state = cur
    if run.get("cancelled") or cur == "cancelled":
        state = "cancelled"
        run["cancelled"] = True
    engine.store.put_run(run_id, run, state)


def _materialize_adapt_run(
    engine: Any, response: dict[str, Any], blob_keys: list[str]
) -> None:
    digests = [str(d) for d in (response.get("digests") or blob_keys) if d]
    for digest in digests:
        _ensure_asset_record(engine, digest, None)
    outputs = response.get("outputs") or []
    for row in outputs:
        if isinstance(row, dict) and row.get("digest"):
            _ensure_asset_record(engine, str(row["digest"]), None)
    cache = getattr(engine, "_adapt_run_cache", None)
    if cache is None:
        cache = {}
        engine._adapt_run_cache = cache
    op_key = str(response.get("source_asset") or digests[0] if digests else "adapt")
    cache[op_key] = response


def _materialize_adapt_batch(engine: Any, response: dict[str, Any]) -> None:
    batch_id = str(response.get("batch_id") or "")
    if not batch_id:
        return
    batches = getattr(engine, "_adapt_batches", None)
    if batches is None:
        batches = {}
        engine._adapt_batches = batches
    batches[batch_id] = response
    for item in response.get("items") or []:
        if not isinstance(item, dict):
            continue
        aid = item.get("asset_id") or item.get("output_asset_id")
        if aid:
            _ensure_asset_record(engine, str(aid), None)


def _materialize_collab(engine: Any, response: dict[str, Any]) -> None:
    sid = str(response.get("id") or "")
    if not sid:
        return
    collab_dir = engine._collab_dir()
    path = collab_dir / f"{sid}.json"
    path.write_text(json.dumps(response), encoding="utf-8")


def adapt_run_replay_complete(engine: Any, response: dict[str, Any]) -> bool:
    digests = [str(d) for d in (response.get("digests") or []) if d]
    if not digests:
        return bool(response.get("outputs"))
    for digest in digests:
        if not engine.cas.exists(digest):
            return False
        if engine.store.get_asset(digest) is None:
            return False
    return True


def has_run_output_receipt(journal: DurableJournal, parent_op_id: str) -> bool:
    receipt_op = f"{parent_op_id}:output"
    row = journal.get_operation(receipt_op)
    return row is not None and row.get("status") == "committed"
