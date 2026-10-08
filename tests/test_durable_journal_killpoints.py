from __future__ import annotations

import json
from pathlib import Path

import pytest
from vinci_storage.durable_journal import (
    JournalConfigError,
    JournalError,
    LocalDurableJournal,
    journal_from_env,
    ordered_blob_then_commit,
)
from vinci_storage.durable_paths import MUTATION_RULES, classify_mutation
from vinci_storage.journal_payload import payload_digest


def test_all_mutation_paths_classify() -> None:
    samples = [
        ("POST", "/init", "init"),
        ("PATCH", "/settings", "settings"),
        ("POST", "/runs", "run_accept"),
        ("POST", "/runs/r1/approve", "run_approve"),
        ("POST", "/assets", "asset_upload"),
        ("POST", "/mcp", "mcp_rpc"),
    ]
    for method, path, kind in samples:
        assert classify_mutation(method, path) == kind
    assert len(MUTATION_RULES) >= 18


def test_do_mode_fail_closed_without_journal_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VINCI_DURABLE_JOURNAL", "do")
    monkeypatch.delenv("VINCI_DO_JOURNAL_BASE", raising=False)
    with pytest.raises(JournalConfigError):
        journal_from_env(tmp_path)


def test_ack_survives_commit_and_idempotent_retry(tmp_path: Path) -> None:
    journal = LocalDurableJournal(tmp_path / "journal.sqlite")
    token = journal.acquire_writer()
    op_id = "fixed-op-1"
    payload = {"skill": "@demo"}
    journal.prepare_operation(
        token,
        op_id=op_id,
        kind="run_accept",
        path="/runs",
        blob_keys=[],
        payload=payload,
    )
    journal.commit_ack(
        token,
        kind="run_accept",
        path="/runs",
        blob_keys=[],
        payload=payload,
        response={"run_id": "r1", "state": "pending"},
        op_id=op_id,
    )
    row = journal.get_operation(op_id)
    assert row is not None
    assert row["status"] == "committed"
    prepared = journal.prepare_operation(
        token,
        op_id=op_id,
        kind="run_accept",
        path="/runs",
        blob_keys=[],
        payload=payload,
    )
    assert prepared.cached_response is not None
    assert prepared.cached_response["run_id"] == "r1"


def test_payload_conflict_rejected(tmp_path: Path) -> None:
    journal = LocalDurableJournal(tmp_path / "journal.sqlite")
    token = journal.acquire_writer()
    op_id = "op-conflict"
    journal.prepare_operation(
        token,
        op_id=op_id,
        kind="settings",
        path="/settings",
        blob_keys=[],
        payload={"preference": "cheapest"},
    )
    with pytest.raises(JournalError, match="payload conflict"):
        journal.prepare_operation(
            token,
            op_id=op_id,
            kind="settings",
            path="/settings",
            blob_keys=[],
            payload={"preference": "fastest"},
        )


def test_takeover_invalidates_stale_commit_token(tmp_path: Path) -> None:
    journal = LocalDurableJournal(tmp_path / "journal.sqlite")
    stale = journal.acquire_writer()
    journal.release_writer(stale)
    journal.acquire_writer()
    with pytest.raises(JournalError):
        journal.commit_ack(
            stale,
            kind="run_accept",
            path="/runs",
            blob_keys=[],
            payload={},
            response={"run_id": "lost"},
            op_id="lost-op",
        )


def test_released_writer_rejected_at_commit(tmp_path: Path) -> None:
    journal = LocalDurableJournal(tmp_path / "journal.sqlite")
    token = journal.acquire_writer()
    journal.release_writer(token)
    with pytest.raises(JournalError):
        journal.prepare_operation(
            token,
            op_id="after-release",
            kind="settings",
            path="/settings",
            blob_keys=[],
            payload={"preference": "cheapest"},
        )


def test_blob_required_before_commit(tmp_path: Path) -> None:
    journal = LocalDurableJournal(tmp_path / "journal.sqlite")
    token = journal.acquire_writer()
    with pytest.raises(JournalError):
        journal.prepare_operation(
            token,
            op_id="asset-1",
            kind="asset_upload",
            path="/assets",
            blob_keys=[""],
            payload={},
        )


def test_first_snapshot_style_commit_with_blob(tmp_path: Path) -> None:
    journal = LocalDurableJournal(tmp_path / "journal.sqlite")
    token = journal.acquire_writer()
    blob_key = "home/snapshots/1.fence.attempt.tar.gz"
    payload = {"filename": "a.png"}
    op_id = ordered_blob_then_commit(
        journal,
        token,
        kind="asset_upload",
        path="/assets",
        payload=payload,
        blob_keys=[blob_key],
        response={"id": blob_key, "mime": "image/png"},
    )
    stored = journal.get_operation(op_id)
    assert stored is not None
    keys = json.loads(stored["blob_keys_json"])
    assert keys == [blob_key]
    assert stored["payload_digest"] == payload_digest(payload)


def test_outbox_pending_after_commit(tmp_path: Path) -> None:
    journal = LocalDurableJournal(tmp_path / "journal.sqlite")
    token = journal.acquire_writer()
    op_id = "settings-op"
    payload = {"preference": "cheapest"}
    journal.prepare_operation(
        token,
        op_id=op_id,
        kind="settings",
        path="/settings",
        blob_keys=[],
        payload=payload,
    )
    journal.commit_ack(
        token,
        kind="settings",
        path="/settings",
        blob_keys=[],
        payload=payload,
        response={"preference": "cheapest"},
        op_id=op_id,
    )
    pending = journal.list_pending_outbox()
    assert len(pending) == 1
    journal.mark_outbox_dispatched(op_id)
    assert journal.list_pending_outbox() == []
