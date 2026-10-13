from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from vinci_core.redact import redact_mapping
from vinci_protocol.models import Asset, Event, Job, Receipt

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  workflow_run_id TEXT,
  node_id TEXT,
  model_id TEXT NOT NULL,
  provider_job_ref TEXT,
  state TEXT NOT NULL,
  inputs TEXT NOT NULL,
  outputs TEXT NOT NULL,
  estimate TEXT,
  receipt TEXT,
  error TEXT,
  timings TEXT,
  retries INTEGER NOT NULL DEFAULT 0,
  idempotency_key TEXT,
  protocol_version TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_idempotency ON jobs(idempotency_key);
CREATE TABLE IF NOT EXISTS receipts (
  job_id TEXT PRIMARY KEY,
  body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  type TEXT NOT NULL,
  job_id TEXT,
  run_id TEXT,
  payload TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS assets (
  id TEXT PRIMARY KEY,
  body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  body TEXT NOT NULL,
  state TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


class SqliteStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def put_job(self, job: Job, secret_values: list[str] | None = None) -> None:
        dumped = redact_mapping(job.model_dump(mode="json"), extra_values=secret_values)
        now = _now()
        self._conn.execute(
            """
            INSERT INTO jobs (
              id, workflow_run_id, node_id, model_id, provider_job_ref, state,
              inputs, outputs, estimate, receipt, error, timings, retries,
              idempotency_key, protocol_version, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              state=excluded.state,
              provider_job_ref=excluded.provider_job_ref,
              outputs=excluded.outputs,
              estimate=excluded.estimate,
              receipt=excluded.receipt,
              error=excluded.error,
              timings=excluded.timings,
              retries=excluded.retries,
              updated_at=excluded.updated_at
            """,
            (
                dumped["id"],
                dumped.get("workflow_run_id"),
                dumped.get("node_id"),
                dumped["model_id"],
                dumped.get("provider_job_ref"),
                dumped["state"],
                json.dumps(dumped.get("inputs") or {}),
                json.dumps(dumped.get("outputs") or []),
                json.dumps(dumped.get("estimate")),
                json.dumps(dumped.get("receipt")),
                json.dumps(dumped.get("error")),
                json.dumps(dumped.get("timings") or {}),
                dumped.get("retries") or 0,
                dumped.get("idempotency_key"),
                dumped.get("protocol_version"),
                now,
                now,
            ),
        )
        self._conn.commit()

    def get_job(self, job_id: str) -> Job | None:
        row = self._conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            return None
        payload = {
            "id": row["id"],
            "workflow_run_id": row["workflow_run_id"],
            "node_id": row["node_id"],
            "model_id": row["model_id"],
            "provider_job_ref": row["provider_job_ref"],
            "state": row["state"],
            "inputs": json.loads(row["inputs"]),
            "outputs": json.loads(row["outputs"]),
            "estimate": json.loads(row["estimate"]) if row["estimate"] else None,
            "receipt": json.loads(row["receipt"]) if row["receipt"] else None,
            "error": json.loads(row["error"]) if row["error"] else None,
            "timings": json.loads(row["timings"]) if row["timings"] else {},
            "retries": row["retries"],
            "idempotency_key": row["idempotency_key"],
            "protocol_version": row["protocol_version"],
        }
        return Job.model_validate(payload)

    def find_by_idempotency(self, key: str) -> Job | None:
        row = self._conn.execute(
            "SELECT id FROM jobs WHERE idempotency_key=? AND state='completed' "
            "ORDER BY created_at LIMIT 1",
            (key,),
        ).fetchone()
        if row is None:
            return None
        return self.get_job(row["id"])

    def list_jobs(self, run_id: str | None = None) -> list[Job]:
        if run_id:
            rows = self._conn.execute(
                "SELECT id FROM jobs WHERE workflow_run_id=? ORDER BY created_at",
                (run_id,),
            ).fetchall()
        else:
            rows = self._conn.execute("SELECT id FROM jobs ORDER BY created_at").fetchall()
        jobs: list[Job] = []
        for row in rows:
            job = self.get_job(row["id"])
            if job is not None:
                jobs.append(job)
        return jobs

    def put_receipt(self, receipt: Receipt, secret_values: list[str] | None = None) -> None:
        body = redact_mapping(receipt.model_dump(mode="json"), extra_values=secret_values)
        self._conn.execute(
            "INSERT OR REPLACE INTO receipts(job_id, body) VALUES (?, ?)",
            (receipt.job_id, json.dumps(body)),
        )
        self._conn.commit()

    def get_receipt(self, job_id: str) -> Receipt | None:
        row = self._conn.execute("SELECT body FROM receipts WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            return None
        return Receipt.model_validate(json.loads(row["body"]))

    def append_event(self, event: Event, secret_values: list[str] | None = None) -> None:
        payload = redact_mapping(event.payload, extra_values=secret_values)
        dumped = event.model_dump(mode="json")
        self._conn.execute(
            "INSERT INTO events(type, job_id, run_id, payload, created_at) VALUES (?, ?, ?, ?, ?)",
            (
                dumped["type"],
                dumped.get("job_id"),
                dumped.get("run_id"),
                json.dumps(payload),
                dumped["created_at"],
            ),
        )
        self._conn.commit()

    def list_receipts(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT body FROM receipts").fetchall()
        return [json.loads(row["body"]) for row in rows]

    def put_run(self, run_id: str, body: dict[str, Any], state: str) -> None:
        dumped = redact_mapping(body)
        dumped.pop("id", None)
        now = _now()
        self._conn.execute(
            """
            INSERT INTO runs(id, body, state, created_at) VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET body=excluded.body, state=excluded.state
            """,
            (run_id, json.dumps(dumped), state, now),
        )
        self._conn.commit()

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT id, body, state, created_at FROM runs WHERE id=?", (run_id,)
        ).fetchone()
        if row is None:
            return None
        body = json.loads(row["body"])
        payload: dict[str, Any] = dict(body) if isinstance(body, dict) else {}
        payload["id"] = row["id"]
        payload["state"] = row["state"]
        payload.setdefault("created_at", row["created_at"])
        return payload

    def list_runs(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT id FROM runs ORDER BY created_at").fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            item = self.get_run(row["id"])
            if item is not None:
                out.append(item)
        return out

    def list_events(self, run_id: str | None = None, after_id: int = 0) -> list[dict[str, Any]]:
        if run_id:
            rows = self._conn.execute(
                "SELECT id, type, job_id, run_id, payload, created_at FROM events "
                "WHERE run_id=? AND id>? ORDER BY id",
                (run_id, after_id),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, type, job_id, run_id, payload, created_at FROM events "
                "WHERE id>? ORDER BY id",
                (after_id,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "type": row["type"],
                "job_id": row["job_id"],
                "run_id": row["run_id"],
                "payload": json.loads(row["payload"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def put_asset(self, asset: Asset, secret_values: list[str] | None = None) -> None:
        body = redact_mapping(asset.model_dump(mode="json"), extra_values=secret_values)
        self._conn.execute(
            "INSERT OR REPLACE INTO assets(id, body) VALUES (?, ?)",
            (asset.id, json.dumps(body)),
        )
        self._conn.commit()

    def get_asset(self, asset_id: str) -> Asset | None:
        row = self._conn.execute("SELECT body FROM assets WHERE id=?", (asset_id,)).fetchone()
        if row is None:
            return None
        return Asset.model_validate(json.loads(row["body"]))

    def list_assets(self) -> list[Asset]:
        rows = self._conn.execute("SELECT body FROM assets").fetchall()
        return [Asset.model_validate(json.loads(row["body"])) for row in rows]

    def month_spend(self, year_month: str | None = None) -> float:
        prefix = year_month or datetime.now(tz=UTC).strftime("%Y-%m")
        total = 0.0
        for row in self._conn.execute(
            "SELECT receipt, updated_at FROM jobs WHERE state='completed'"
        ).fetchall():
            if not str(row["updated_at"]).startswith(prefix):
                continue
            receipt = json.loads(row["receipt"]) if row["receipt"] else None
            if receipt and str(receipt.get("currency") or "USD").upper() == "USD":
                total += float(receipt.get("computed_cost") or 0)
        return total
