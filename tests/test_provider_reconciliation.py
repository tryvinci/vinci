"""Provider inflight ledger helpers."""

from __future__ import annotations

import pytest
from vinci_runtime.provider_reconciliation import (
    ledger_provider_inflight_op_id,
    load_ledger_provider_inflight,
    provider_inflight_pending_without_ref,
    supports_durable_reconciliation,
)
from vinci_storage.durable_journal import JournalError, LocalDurableJournal
from vinci_storage.journal_payload import normalize_do_journal_base, payload_digest


def test_normalize_do_journal_base() -> None:
    assert (
        normalize_do_journal_base("https://worker.example.dev")
        == "https://worker.example.dev/__vinci/journal"
    )
    full = "https://worker.example.dev/__vinci/journal"
    assert normalize_do_journal_base(full) == full
    assert normalize_do_journal_base(f"{full}/") == full


def test_ledger_provider_inflight_op_id_format() -> None:
    assert ledger_provider_inflight_op_id("op-1", "gen") == "op-1:provider_inflight:gen"


def test_load_ledger_provider_inflight_committed(tmp_path) -> None:
    journal = LocalDurableJournal(tmp_path / "ledger.sqlite")
    token = journal.acquire_writer()
    op_id = ledger_provider_inflight_op_id("parent", "n0")
    payload = {
        "run_id": "r1",
        "node_id": "n0",
        "job_id": "j1",
        "provider_job_ref": "ref-abc",
        "provider": "openai",
    }
    journal.prepare_operation(
        token, op_id=op_id, kind="provider_inflight", path="/x", blob_keys=[], payload=payload
    )
    journal.commit_ack(
        token,
        kind="provider_inflight",
        path="/x",
        blob_keys=[],
        payload=payload,
        response=payload,
        op_id=op_id,
    )
    row = load_ledger_provider_inflight(journal, "parent", "n0")
    assert row is not None
    assert row["provider_job_ref"] == "ref-abc"


def test_provider_inflight_pending_without_ref(tmp_path) -> None:
    journal = LocalDurableJournal(tmp_path / "ledger.sqlite")
    token = journal.acquire_writer()
    op_id = ledger_provider_inflight_op_id("parent", "n0")
    payload = {
        "run_id": "r1",
        "node_id": "n0",
        "job_id": "j1",
        "provider_job_ref": "",
        "submit_intent": True,
    }
    journal.prepare_operation(
        token, op_id=op_id, kind="provider_inflight", path="/x", blob_keys=[], payload=payload
    )
    pending = provider_inflight_pending_without_ref(journal, "parent", "n0")
    assert pending is not None
    assert pending["job_id"] == "j1"
    assert load_ledger_provider_inflight(journal, "parent", "n0") is None


def test_commit_ack_submit_intent_ref_upgrade(tmp_path) -> None:
    journal = LocalDurableJournal(tmp_path / "ledger.sqlite")
    token = journal.acquire_writer()
    op_id = ledger_provider_inflight_op_id("parent", "adapt:0")
    intent = {
        "run_id": "parent",
        "node_id": "adapt:0",
        "job_id": "j1",
        "model_id": "m1",
        "provider": "openai",
        "provider_job_ref": "",
        "idempotency_key": "k1",
        "submit_intent": True,
    }
    journal.prepare_operation(
        token, op_id=op_id, kind="provider_inflight", path="/x", blob_keys=[], payload=intent
    )
    committed = dict(intent)
    committed["provider_job_ref"] = "ref-xyz"
    committed.pop("submit_intent", None)
    journal.commit_ack(
        token,
        kind="provider_inflight",
        path="/x",
        blob_keys=[],
        payload=committed,
        response=committed,
        op_id=op_id,
    )
    row = journal.get_operation(op_id)
    assert row is not None
    assert row["status"] == "committed"
    assert load_ledger_provider_inflight(journal, "parent", "adapt:0") is not None


_SUBMIT_INTENT_BASE = {
    "run_id": "parent",
    "node_id": "adapt:0",
    "job_id": "j1",
    "model_id": "m1",
    "provider": "openai",
    "provider_job_ref": "",
    "idempotency_key": "k1",
    "submit_intent": True,
}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("run_id", "other-run"),
        ("node_id", "other-node"),
        ("job_id", "other-job"),
        ("model_id", "other-model"),
        ("provider", "other-provider"),
        ("idempotency_key", "other-key"),
    ],
)
def test_commit_ack_submit_intent_rejects_payload_field_mutation(
    tmp_path, field: str, value: str
) -> None:
    journal = LocalDurableJournal(tmp_path / "ledger.sqlite")
    token = journal.acquire_writer()
    op_id = ledger_provider_inflight_op_id("parent", "adapt:0")
    intent = dict(_SUBMIT_INTENT_BASE)
    journal.prepare_operation(
        token,
        op_id=op_id,
        kind="provider_inflight",
        path="/runs/parent/nodes/adapt:0/provider_inflight",
        blob_keys=[],
        payload=intent,
    )
    mutated = dict(intent)
    mutated[field] = value
    mutated["provider_job_ref"] = "ref-ok"
    mutated.pop("submit_intent", None)
    with pytest.raises(JournalError, match="payload conflict"):
        journal.commit_ack(
            token,
            kind="provider_inflight",
            path="/runs/parent/nodes/adapt:0/provider_inflight",
            blob_keys=[],
            payload=mutated,
            response=mutated,
            op_id=op_id,
        )


def test_commit_ack_submit_intent_rejects_kind_mutation(tmp_path) -> None:
    journal = LocalDurableJournal(tmp_path / "ledger.sqlite")
    token = journal.acquire_writer()
    op_id = ledger_provider_inflight_op_id("parent", "adapt:0")
    intent = dict(_SUBMIT_INTENT_BASE)
    journal.prepare_operation(
        token,
        op_id=op_id,
        kind="provider_inflight",
        path="/runs/parent/nodes/adapt:0/provider_inflight",
        blob_keys=[],
        payload=intent,
    )
    committed = dict(intent)
    committed["provider_job_ref"] = "ref-ok"
    committed.pop("submit_intent", None)
    with pytest.raises(JournalError, match="payload conflict"):
        journal.commit_ack(
            token,
            kind="other_kind",
            path="/runs/parent/nodes/adapt:0/provider_inflight",
            blob_keys=[],
            payload=committed,
            response=committed,
            op_id=op_id,
        )


def test_commit_ack_submit_intent_rejects_path_mutation(tmp_path) -> None:
    journal = LocalDurableJournal(tmp_path / "ledger.sqlite")
    token = journal.acquire_writer()
    op_id = ledger_provider_inflight_op_id("parent", "adapt:0")
    intent = dict(_SUBMIT_INTENT_BASE)
    journal.prepare_operation(
        token,
        op_id=op_id,
        kind="provider_inflight",
        path="/runs/parent/nodes/adapt:0/provider_inflight",
        blob_keys=[],
        payload=intent,
    )
    committed = dict(intent)
    committed["provider_job_ref"] = "ref-ok"
    committed.pop("submit_intent", None)
    with pytest.raises(JournalError, match="payload conflict"):
        journal.commit_ack(
            token,
            kind="provider_inflight",
            path="/other/path",
            blob_keys=[],
            payload=committed,
            response=committed,
            op_id=op_id,
        )


def test_commit_ack_rejects_unrelated_pending_digest_change(tmp_path) -> None:
    journal = LocalDurableJournal(tmp_path / "ledger.sqlite")
    token = journal.acquire_writer()
    op_id = ledger_provider_inflight_op_id("parent", "n0")
    intent = {
        "run_id": "r1",
        "node_id": "n0",
        "job_id": "j1",
        "provider_job_ref": "",
    }
    journal.prepare_operation(
        token, op_id=op_id, kind="provider_inflight", path="/x", blob_keys=[], payload=intent
    )
    bad = {**intent, "provider_job_ref": "ref-1", "extra": "changed"}
    assert payload_digest(intent) != payload_digest(bad)
    with pytest.raises(JournalError, match="payload conflict"):
        journal.commit_ack(
            token,
            kind="provider_inflight",
            path="/x",
            blob_keys=[],
            payload=bad,
            response=bad,
            op_id=op_id,
        )


def test_supports_durable_reconciliation_flags() -> None:
    class _Yes:
        durable_job_reconciliation = True

    class _No:
        durable_job_reconciliation = False

    assert supports_durable_reconciliation(_Yes()) is True
    assert supports_durable_reconciliation(_No()) is False
