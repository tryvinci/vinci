"""Canonical adapt-batch capture + restore (home batches/*.json, not memory attrs)."""

from __future__ import annotations

import json
from typing import Any

from vinci_storage.durable_journal import CommitResult, DurableJournal, JournalError

from vinci_daemon.ledger_child_commit import child_bundle_committed, commit_child_operation


def capture_adapt_batch_bundle(engine: Any, batch_id: str) -> dict[str, Any]:
    path = engine._batch_path(batch_id)
    if not path.is_file():
        raise JournalError(f"adapt_batch file missing: {batch_id}")
    batch_file = json.loads(path.read_text(encoding="utf-8"))
    try:
        status = engine.adapt_batch_status(batch_id)
    except KeyError as exc:
        raise JournalError(f"adapt_batch status unavailable: {batch_id}") from exc
    runs: list[dict[str, Any]] = []
    jobs: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    assets: list[dict[str, Any]] = []
    seen_assets: set[str] = set()
    for item in batch_file.get("items") or []:
        if not isinstance(item, dict):
            continue
        run_id = item.get("run_id")
        if not run_id:
            continue
        run = engine.store.get_run(str(run_id))
        if run is None:
            raise JournalError(f"adapt_batch run missing from store: {run_id}")
        runs.append(dict(run))
        for jid in run.get("job_ids") or []:
            job = engine.store.get_job(str(jid))
            if job is None:
                raise JournalError(f"adapt_batch job missing: {jid}")
            jobs.append(job.model_dump(mode="json"))
            if job.receipt is not None:
                receipts.append(job.receipt.model_dump(mode="json"))
        for digest in run.get("outputs") or []:
            d = str(digest)
            if d in seen_assets:
                continue
            seen_assets.add(d)
            if not engine.cas.exists(d):
                raise JournalError(f"adapt_batch cas missing: {d}")
            meta = engine.store.get_asset(d)
            if meta is None:
                raise JournalError(f"adapt_batch asset metadata missing: {d}")
            assets.append(meta.model_dump(mode="json"))
    for item in status.get("items") or []:
        if not isinstance(item, dict):
            continue
        for aid in item.get("output_asset_ids") or []:
            d = str(aid)
            if d in seen_assets:
                continue
            seen_assets.add(d)
            if not engine.cas.exists(d):
                raise JournalError(f"adapt_batch output cas missing: {d}")
            meta = engine.store.get_asset(d)
            if meta is None:
                raise JournalError(f"adapt_batch output asset missing: {d}")
            assets.append(meta.model_dump(mode="json"))
    return {
        "kind": "adapt_batch",
        "batch_id": batch_id,
        "batch_file": batch_file,
        "batch_status": status,
        "runs": runs,
        "jobs": jobs,
        "receipts": receipts,
        "assets": assets,
    }


def adapt_batch_parent_snapshot(engine: Any, batch_id: str) -> dict[str, Any]:
    """Queued batch intent persisted on parent ack (before terminal bundle)."""
    path = engine._batch_path(batch_id)
    if not path.is_file():
        raise JournalError(f"adapt_batch parent snapshot missing file: {batch_id}")
    batch_file = json.loads(path.read_text(encoding="utf-8"))
    queued_runs: list[dict[str, Any]] = []
    for item in batch_file.get("items") or []:
        if not isinstance(item, dict):
            continue
        run_id = item.get("run_id")
        if not run_id:
            continue
        run = engine.store.get_run(str(run_id))
        if run is None:
            raise JournalError(f"adapt_batch queued run missing: {run_id}")
        queued_runs.append(
            {
                "index": item.get("index"),
                "run_id": str(run_id),
                "run": dict(run),
            }
        )
    return {
        "batch_id": batch_id,
        "batch_file": batch_file,
        "queued_runs": queued_runs,
    }


def enrich_adapt_batch_response(engine: Any, response: dict[str, Any]) -> dict[str, Any]:
    batch_id = str(response.get("batch_id") or "")
    if not batch_id:
        raise JournalError("adapt_batch response missing batch_id")
    snapshot = adapt_batch_parent_snapshot(engine, batch_id)
    return {**response, **snapshot}


def restore_adapt_batch_parent_snapshot(
    engine: Any,
    snapshot: dict[str, Any],
    journal: DurableJournal | None = None,
    parent_op_id: str | None = None,
) -> None:
    batch_id = str(snapshot.get("batch_id") or "")
    batch_file = snapshot.get("batch_file")
    if not batch_id or not isinstance(batch_file, dict):
        raise RuntimeError("adapt_batch parent snapshot incomplete")
    from vinci_daemon.ledger_replay import _materialize_run, has_run_output_receipt

    for entry in snapshot.get("queued_runs") or []:
        if not isinstance(entry, dict):
            continue
        index = entry.get("index")
        if (
            journal is not None
            and parent_op_id is not None
            and index is not None
            and has_run_output_receipt(journal, f"{parent_op_id}:item:{index}")
        ):
            continue
        run = entry.get("run")
        if isinstance(run, dict) and run.get("id"):
            run_id = str(run["id"])
            existing = engine.store.get_run(run_id)
            if existing is not None and str(existing.get("state") or "") in {
                "completed",
                "failed",
                "cancelled",
            }:
                continue
            _materialize_run(engine, run)
    path = engine._batch_path(batch_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(batch_file, indent=2), encoding="utf-8")


def restore_adapt_batch_bundle(engine: Any, bundle: dict[str, Any]) -> None:
    batch_id = str(bundle.get("batch_id") or "")
    batch_file = bundle.get("batch_file")
    if not batch_id or not isinstance(batch_file, dict):
        raise RuntimeError("adapt_batch bundle incomplete")
    from vinci_daemon.ledger_replay import (
        _materialize_jobs_and_receipts,
        _materialize_run,
    )

    for run in bundle.get("runs") or []:
        if isinstance(run, dict) and run.get("id"):
            _materialize_run(engine, run)
    _materialize_jobs_and_receipts(
        engine,
        {
            "jobs": bundle.get("jobs") or [],
            "receipts": bundle.get("receipts") or [],
            "assets": bundle.get("assets") or [],
        },
    )
    path = engine._batch_path(batch_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(batch_file, indent=2), encoding="utf-8")


def commit_adapt_batch_bundle(
    journal: DurableJournal,
    token: CommitResult,
    engine: Any,
    parent_op_id: str,
    batch_id: str,
) -> dict[str, Any]:
    if not adapt_batch_terminal(engine, batch_id):
        raise JournalError(f"adapt_batch {batch_id} not terminal; cannot commit bundle")
    bundle = capture_adapt_batch_bundle(engine, batch_id)
    bundle_op = f"{parent_op_id}:batch_bundle"
    blob_keys = [str(a["id"]) for a in bundle.get("assets") or [] if isinstance(a, dict)]
    payload = {"parent_op_id": parent_op_id, "batch_id": batch_id}
    return commit_child_operation(
        journal,
        token,
        op_id=bundle_op,
        kind="adapt_batch_bundle",
        path=f"/adapts/batch/{batch_id}/bundle",
        payload=payload,
        blob_keys=blob_keys,
        response=bundle,
        exit_after_prepare_env="VINCI_TEST_EXIT_AFTER_BUNDLE_PREPARE",
    )


def ensure_adapt_batch_outbox_complete(
    journal: DurableJournal,
    engine: Any,
    parent_op_id: str,
    parent_response: dict[str, Any],
) -> None:
    """Dispatch item runs, commit terminal bundle, then caller may mark outbox done."""
    if child_bundle_committed(journal, parent_op_id, "batch_bundle"):
        return
    batch_id = str(parent_response.get("batch_id") or "")
    if not batch_id:
        raise JournalError("adapt_batch missing batch_id")
    token = getattr(engine, "_journal_token", None)
    if token is None:
        raise JournalError("journal writer token required for adapt_batch bundle")
    path = engine._batch_path(batch_id)
    if not path.is_file():
        if parent_response.get("batch_file"):
            restore_adapt_batch_parent_snapshot(
                engine, parent_response, journal, parent_op_id
            )
        else:
            raise JournalError(f"adapt_batch file missing for {batch_id}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    from vinci_daemon.durable_receipts import try_resume_pending_run_output
    from vinci_daemon.ledger_replay import has_run_output_receipt

    for item in raw.get("items") or []:
        if not isinstance(item, dict):
            continue
        run_id = item.get("run_id")
        if not run_id:
            continue
        run = engine.store.get_run(str(run_id))
        if run is None:
            raise JournalError(f"adapt_batch run {run_id} not materialized")
        state = str(run.get("state") or "")
        item_key = f"{parent_op_id}:item:{item.get('index')}"
        if token is not None:
            try_resume_pending_run_output(journal, token, engine, item_key)
        if has_run_output_receipt(journal, item_key):
            if state not in {"completed", "failed", "cancelled"} and not item.get("error"):
                raise JournalError(
                    f"adapt_batch item {item.get('index')} has output receipt but state={state}"
                )
            continue
        if state == "queued":
            engine.dispatch_run(
                str(run_id),
                operation_id=item_key,
                receipt_parent_op_id=item_key,
            )
            run = engine.store.get_run(str(run_id)) or run
            state = str(run.get("state") or "")
        if state == "completed" and not has_run_output_receipt(journal, item_key):
            raise JournalError(f"adapt_batch item {item.get('index')} missing output receipt")
        if state not in {"completed", "failed", "cancelled"} and not item.get("error"):
            raise JournalError(f"adapt_batch run {run_id} not terminal ({state})")
    if not adapt_batch_terminal(engine, batch_id):
        raise JournalError(f"adapt_batch {batch_id} not terminal")
    commit_adapt_batch_bundle(journal, token, engine, parent_op_id, batch_id)
    if not child_bundle_committed(journal, parent_op_id, "batch_bundle"):
        raise JournalError("adapt_batch bundle commit did not persist")


def adapt_batch_terminal(engine: Any, batch_id: str) -> bool:
    try:
        status = engine.adapt_batch_status(batch_id)
    except KeyError:
        return False
    for item in status.get("items") or []:
        if not isinstance(item, dict):
            continue
        st = str(item.get("status") or "")
        if st in {"running", "queued", "pending"}:
            return False
    return True
