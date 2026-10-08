"""Durable operation journal: blob-first, intent-before-handler, commit before HTTP ack."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib import error, request

from vinci_storage.committed_cursor import (
    CommittedCursor,
    cursor_from_api_payload,
    next_cursor_from_page,
)
from vinci_storage.journal_payload import (
    allow_provider_submit_ref_upgrade,
    normalize_do_journal_base,
    payload_digest,
)

LOG = logging.getLogger("vinci.durable_journal")

JournalMode = Literal["off", "local", "do"]


class JournalError(RuntimeError):
    pass


class JournalConfigError(JournalError):
    pass


@dataclass(frozen=True)
class CommitResult:
    op_id: str
    generation: int
    fence_token: str


@dataclass(frozen=True)
class PrepareResult:
    """If cached_response is set, skip handler and return it."""

    op_id: str
    cached_response: dict[str, Any] | None = None


class DurableJournal(ABC):
    @abstractmethod
    def healthy(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def last_error(self) -> str | None:
        raise NotImplementedError

    @abstractmethod
    def acquire_writer(self) -> CommitResult:
        raise NotImplementedError

    @abstractmethod
    def renew_writer(self, token: CommitResult) -> CommitResult:
        raise NotImplementedError

    @abstractmethod
    def release_writer(self, token: CommitResult) -> None:
        raise NotImplementedError

    @abstractmethod
    def prepare_operation(
        self,
        token: CommitResult,
        *,
        op_id: str,
        kind: str,
        path: str,
        blob_keys: list[str],
        payload: dict[str, Any],
    ) -> PrepareResult:
        """Record durable intent before handler side effects."""
        raise NotImplementedError

    @abstractmethod
    def commit_ack(
        self,
        token: CommitResult,
        *,
        kind: str,
        path: str,
        blob_keys: list[str],
        payload: dict[str, Any],
        response: dict[str, Any],
        op_id: str,
    ) -> str:
        """Finalize operation after handler; returns operation id."""
        raise NotImplementedError

    @abstractmethod
    def get_operation(self, op_id: str) -> dict[str, Any] | None:
        raise NotImplementedError

    @abstractmethod
    def list_pending_outbox(self, limit: int = 100) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def mark_outbox_dispatched(self, op_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_committed_operations(
        self,
        limit: int = 500,
        cursor: CommittedCursor | None = None,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    def list_committed_operations_page(
        self,
        limit: int = 500,
        cursor: CommittedCursor | None = None,
    ) -> tuple[list[dict[str, Any]], CommittedCursor | None]:
        items = self.list_committed_operations(limit=limit, cursor=cursor)
        return items, next_cursor_from_page(items, limit)

    def iter_committed_operations(self, page_size: int = 500) -> Any:
        """Yield every committed row in stable order (cursor-paginated)."""
        cursor: CommittedCursor | None = None
        while True:
            page, next_cursor = self.list_committed_operations_page(
                limit=page_size, cursor=cursor
            )
            if not page:
                break
            yield from page
            if next_cursor is None:
                break
            cursor = next_cursor


def journal_mode_from_env() -> JournalMode:
    raw = os.environ.get("VINCI_DURABLE_JOURNAL", "off").strip().lower()
    if raw in {"0", "off", "false", "no"}:
        return "off"
    if raw == "do":
        return "do"
    if raw == "local":
        return "local"
    return "off"


def journal_db_path(home: Path) -> Path:
    override = os.environ.get("VINCI_DURABLE_JOURNAL_PATH", "").strip()
    if override:
        return Path(override).expanduser()
    return home / "durable-journal.sqlite"


def journal_from_env(home: Path) -> DurableJournal | None:
    mode = journal_mode_from_env()
    if mode == "off":
        return None
    if mode == "do":
        base = normalize_do_journal_base(os.environ.get("VINCI_DO_JOURNAL_BASE", ""))
        if not base:
            raise JournalConfigError(
                "VINCI_DURABLE_JOURNAL=do requires VINCI_DO_JOURNAL_BASE "
                "(worker origin or /__vinci/journal prefix; fail closed)"
            )
        return DoJournalClient(base_url=base)
    return LocalDurableJournal(journal_db_path(home))


def _parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class LocalDurableJournal(DurableJournal):
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._healthy = True
        self._last_error: str | None = None
        path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS writer_lease (
                  id INTEGER PRIMARY KEY CHECK (id = 1),
                  generation INTEGER NOT NULL,
                  fence_token TEXT NOT NULL,
                  writer_id TEXT NOT NULL,
                  lease_until TEXT NOT NULL,
                  released INTEGER NOT NULL DEFAULT 0,
                  etag TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS operations (
                  op_id TEXT PRIMARY KEY,
                  generation INTEGER NOT NULL,
                  fence_token TEXT NOT NULL,
                  kind TEXT NOT NULL,
                  path TEXT NOT NULL,
                  blob_keys_json TEXT NOT NULL,
                  payload_json TEXT NOT NULL,
                  payload_digest TEXT NOT NULL DEFAULT '',
                  response_json TEXT NOT NULL,
                  status TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  committed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS outbox (
                  op_id TEXT PRIMARY KEY,
                  dispatch_state TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                """
            )
            cols = [r[1] for r in conn.execute("PRAGMA table_info(operations)").fetchall()]
            if "payload_digest" not in cols:
                conn.execute(
                    "ALTER TABLE operations ADD COLUMN payload_digest TEXT NOT NULL DEFAULT ''"
                )
            conn.commit()

    def healthy(self) -> bool:
        return self._healthy

    def last_error(self) -> str | None:
        return self._last_error

    def _fail(self, message: str) -> None:
        self._healthy = False
        self._last_error = message
        raise JournalError(message)

    def _now(self) -> str:
        return datetime.now(tz=UTC).isoformat()

    def _lease_seconds(self) -> int:
        return int(os.environ.get("VINCI_HOME_LEASE_SECONDS", "120"))

    def _lease_active(self, row: sqlite3.Row) -> bool:
        if int(row["released"]) != 0:
            return False
        try:
            return _parse_iso(str(row["lease_until"])) > datetime.now(tz=UTC)
        except ValueError:
            return False

    def _assert_writer(self, conn: sqlite3.Connection, token: CommitResult) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM writer_lease WHERE id = 1").fetchone()
        if row is None or row["fence_token"] != token.fence_token:
            self._fail("stale writer token")
        lease_row: sqlite3.Row = row
        if int(lease_row["released"]) != 0:
            self._fail("writer lease released")
        if not self._lease_active(lease_row):
            self._fail("writer lease expired")
        return lease_row

    def acquire_writer(self) -> CommitResult:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute("SELECT * FROM writer_lease WHERE id = 1").fetchone()
                if row is not None and self._lease_active(row) and int(row["released"]) == 0:
                    self._fail("active writer lease held elsewhere")
                if row is None:
                    fence = str(uuid.uuid4())
                    gen = 0
                    etag = hashlib.sha256(fence.encode()).hexdigest()
                    conn.execute(
                        """
                        INSERT INTO writer_lease (
                          id, generation, fence_token, writer_id, lease_until, released, etag
                        )
                        VALUES (1, ?, ?, ?, ?, 0, ?)
                        """,
                        (gen, fence, "local", self._lease_until_iso(), etag),
                    )
                    conn.commit()
                    return CommitResult(op_id="", generation=gen, fence_token=fence)
                fence = str(uuid.uuid4())
                gen = int(row["generation"]) + 1
                etag = hashlib.sha256(f"{gen}:{fence}".encode()).hexdigest()
                updated = conn.execute(
                    """
                    UPDATE writer_lease
                    SET generation = ?, fence_token = ?, writer_id = ?,
                        lease_until = ?, released = 0, etag = ?
                    WHERE id = 1 AND etag = ?
                    """,
                    (gen, fence, "local", self._lease_until_iso(), etag, row["etag"]),
                )
                if updated.rowcount != 1:
                    self._fail("failed to acquire writer lease (fence conflict)")
                conn.commit()
                return CommitResult(op_id="", generation=gen, fence_token=fence)

    def _lease_until_iso(self) -> str:
        return datetime.fromtimestamp(
            datetime.now(tz=UTC).timestamp() + self._lease_seconds(), tz=UTC
        ).isoformat()

    def renew_writer(self, token: CommitResult) -> CommitResult:
        with self._lock:
            with self._connect() as conn:
                row = self._assert_writer(conn, token)
                etag = hashlib.sha256(f"renew:{token.fence_token}".encode()).hexdigest()
                conn.execute(
                    """
                    UPDATE writer_lease
                    SET lease_until = ?, released = 0, etag = ?
                    WHERE id = 1 AND fence_token = ? AND etag = ?
                    """,
                    (self._lease_until_iso(), etag, token.fence_token, row["etag"]),
                )
                conn.commit()
                return token

    def release_writer(self, token: CommitResult) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE writer_lease SET released = 1
                    WHERE id = 1 AND fence_token = ? AND released = 0
                    """,
                    (token.fence_token,),
                )
                conn.commit()

    def prepare_operation(
        self,
        token: CommitResult,
        *,
        op_id: str,
        kind: str,
        path: str,
        blob_keys: list[str],
        payload: dict[str, Any],
    ) -> PrepareResult:
        digest = payload_digest(payload)
        with self._lock:
            with self._connect() as conn:
                self._assert_writer(conn, token)
                for key in blob_keys:
                    if not key:
                        self._fail("blob key required before intent")
                existing = conn.execute(
                    "SELECT * FROM operations WHERE op_id = ?", (op_id,)
                ).fetchone()
                if existing is not None:
                    if existing["payload_digest"] != digest:
                        self._fail("operation_id payload conflict")
                    if existing["status"] == "committed":
                        return PrepareResult(
                            op_id=op_id,
                            cached_response=json.loads(existing["response_json"]),
                        )
                    return PrepareResult(op_id=op_id, cached_response=None)
                row = self._assert_writer(conn, token)
                now = self._now()
                conn.execute(
                    """
                    INSERT INTO operations (
                      op_id, generation, fence_token, kind, path, blob_keys_json,
                      payload_json, payload_digest, response_json, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}', 'pending', ?)
                    """,
                    (
                        op_id,
                        int(row["generation"]),
                        token.fence_token,
                        kind,
                        path,
                        json.dumps(blob_keys),
                        json.dumps(payload, sort_keys=True),
                        digest,
                        now,
                    ),
                )
                conn.commit()
                return PrepareResult(op_id=op_id, cached_response=None)

    def commit_ack(
        self,
        token: CommitResult,
        *,
        kind: str,
        path: str,
        blob_keys: list[str],
        payload: dict[str, Any],
        response: dict[str, Any],
        op_id: str,
    ) -> str:
        digest = payload_digest(payload)
        with self._lock:
            with self._connect() as conn:
                row = self._assert_writer(conn, token)
                existing = conn.execute(
                    "SELECT * FROM operations WHERE op_id = ?", (op_id,)
                ).fetchone()
                allow_ref_upgrade = False
                if existing is not None:
                    existing_payload = json.loads(existing["payload_json"] or "{}")
                    allow_ref_upgrade = allow_provider_submit_ref_upgrade(
                        str(existing["status"] or ""),
                        existing_payload,
                        payload,
                        existing_kind=str(existing["kind"] or ""),
                        existing_path=str(existing["path"] or ""),
                        commit_kind=kind,
                        commit_path=path,
                    )
                    if existing["payload_digest"] != digest and not allow_ref_upgrade:
                        self._fail("operation_id payload conflict")
                    if existing["status"] == "committed":
                        return op_id
                now = self._now()
                resp_json = json.dumps(response, sort_keys=True, default=str)
                if existing is None:
                    conn.execute(
                        """
                        INSERT INTO operations (
                          op_id, generation, fence_token, kind, path, blob_keys_json,
                          payload_json, payload_digest, response_json, status,
                          created_at, committed_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'committed', ?, ?)
                        """,
                        (
                            op_id,
                            int(row["generation"]),
                            token.fence_token,
                            kind,
                            path,
                            json.dumps(blob_keys),
                            json.dumps(payload, sort_keys=True),
                            digest,
                            resp_json,
                            now,
                            now,
                        ),
                    )
                else:
                    if allow_ref_upgrade:
                        payload_json = json.dumps(payload, sort_keys=True)
                        updated = conn.execute(
                            """
                            UPDATE operations
                            SET payload_json = ?, payload_digest = ?, response_json = ?,
                                status = 'committed', committed_at = ?
                            WHERE op_id = ? AND status = 'pending'
                            """,
                            (payload_json, digest, resp_json, now, op_id),
                        )
                    else:
                        updated = conn.execute(
                            """
                            UPDATE operations
                            SET response_json = ?, status = 'committed', committed_at = ?
                            WHERE op_id = ? AND status = 'pending' AND payload_digest = ?
                            """,
                            (resp_json, now, op_id, digest),
                        )
                    if updated.rowcount != 1:
                        self._fail("commit conflict or stale operation state")
                conn.execute(
                    """
                    INSERT INTO outbox (op_id, dispatch_state, updated_at)
                    VALUES (?, 'pending', ?)
                    ON CONFLICT(op_id) DO NOTHING
                    """,
                    (op_id, now),
                )
                etag = hashlib.sha256(f"commit:{op_id}:{token.fence_token}".encode()).hexdigest()
                conn.execute(
                    """
                    UPDATE writer_lease SET etag = ?, lease_until = ?
                    WHERE id = 1 AND fence_token = ?
                    """,
                    (etag, self._lease_until_iso(), token.fence_token),
                )
                conn.commit()
                return op_id

    def get_operation(self, op_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM operations WHERE op_id = ?", (op_id,)).fetchone()
            if row is None:
                return None
            return dict(row)

    def list_pending_outbox(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT o.* FROM operations o
                JOIN outbox x ON x.op_id = o.op_id
                WHERE x.dispatch_state = 'pending' AND o.status = 'committed'
                ORDER BY o.created_at
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def mark_outbox_dispatched(self, op_id: str) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE outbox SET dispatch_state = 'dispatched', updated_at = ?
                    WHERE op_id = ?
                    """,
                    (self._now(), op_id),
                )
                conn.commit()

    def list_committed_operations(
        self,
        limit: int = 500,
        cursor: CommittedCursor | None = None,
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if cursor is not None:
                rows = conn.execute(
                    """
                    SELECT * FROM operations
                    WHERE status = 'committed'
                      AND (
                        created_at > ?
                        OR (created_at = ? AND op_id > ?)
                      )
                    ORDER BY created_at ASC, op_id ASC
                    LIMIT ?
                    """,
                    (
                        cursor.after_created_at,
                        cursor.after_created_at,
                        cursor.after_op_id,
                        limit,
                    ),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM operations
                    WHERE status = 'committed'
                    ORDER BY created_at ASC, op_id ASC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]


class DoJournalClient(DurableJournal):
    """HTTP client for VinciHost DO journal API."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self._token: CommitResult | None = None
        self._healthy = True
        self._last_error: str | None = None

    def healthy(self) -> bool:
        return self._healthy

    def last_error(self) -> str | None:
        return self._last_error

    def _request(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        data = None
        headers = {
            "content-type": "application/json",
            "user-agent": os.environ.get(
                "VINCI_HTTP_USER_AGENT",
                "vinci-oss-selfhost/1.0 (durable-journal)",
            ),
        }
        token = os.environ.get("VINCI_BRIDGE_TOKEN", "")
        if not token:
            self._healthy = False
            self._last_error = "VINCI_BRIDGE_TOKEN required for DO journal"
            raise JournalError(self._last_error)
        headers["authorization"] = f"Bearer {token}"
        if body is not None:
            data = json.dumps(body).encode("utf-8")
        req = request.Request(url, data=data, method=method, headers=headers)
        try:
            with request.urlopen(req, timeout=60) as resp:  # noqa: S310
                raw = resp.read()
                return json.loads(raw.decode("utf-8")) if raw else {}
        except error.HTTPError as exc:
            self._healthy = False
            self._last_error = exc.read().decode("utf-8", errors="replace")
            raise JournalError(self._last_error) from exc

    def acquire_writer(self) -> CommitResult:
        timeout = float(os.environ.get("VINCI_JOURNAL_LEASE_ACQUIRE_TIMEOUT_SEC", "150"))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                out = self._request("POST", "/acquire", {})
            except JournalError as exc:
                if "lease_active" not in str(exc):
                    raise
                time.sleep(min(2.0, max(0.05, deadline - time.monotonic())))
                continue
            self._token = CommitResult(
                op_id="",
                generation=int(out["generation"]),
                fence_token=str(out["fence_token"]),
            )
            return self._token
        raise JournalError("failed to acquire DO journal writer lease")

    def renew_writer(self, token: CommitResult) -> CommitResult:
        self._request(
            "POST",
            "/renew",
            {"fence_token": token.fence_token, "generation": token.generation},
        )
        self._token = token
        return token

    def release_writer(self, token: CommitResult) -> None:
        self._request(
            "POST",
            "/release",
            {"fence_token": token.fence_token, "generation": token.generation},
        )
        self._token = None

    def prepare_operation(
        self,
        token: CommitResult,
        *,
        op_id: str,
        kind: str,
        path: str,
        blob_keys: list[str],
        payload: dict[str, Any],
    ) -> PrepareResult:
        out = self._request(
            "POST",
            "/intent",
            {
                "fence_token": token.fence_token,
                "generation": token.generation,
                "op_id": op_id,
                "kind": kind,
                "path": path,
                "blob_keys": blob_keys,
                "payload": payload,
            },
        )
        if out.get("cached") and out.get("response") is not None:
            return PrepareResult(op_id=op_id, cached_response=dict(out["response"]))
        return PrepareResult(op_id=op_id, cached_response=None)

    def commit_ack(
        self,
        token: CommitResult,
        *,
        kind: str,
        path: str,
        blob_keys: list[str],
        payload: dict[str, Any],
        response: dict[str, Any],
        op_id: str,
    ) -> str:
        out = self._request(
            "POST",
            "/commit",
            {
                "fence_token": token.fence_token,
                "generation": token.generation,
                "kind": kind,
                "path": path,
                "blob_keys": blob_keys,
                "payload": payload,
                "response": response,
                "op_id": op_id,
            },
        )
        return str(out["op_id"])

    def get_operation(self, op_id: str) -> dict[str, Any] | None:
        out = self._request("GET", f"/operations/{op_id}")
        return out.get("operation")

    def list_pending_outbox(self, limit: int = 100) -> list[dict[str, Any]]:
        out = self._request("GET", f"/outbox/pending?limit={limit}")
        return list(out.get("items", []))

    def mark_outbox_dispatched(self, op_id: str) -> None:
        self._request("POST", "/outbox/dispatch", {"op_id": op_id})

    def list_committed_operations(
        self,
        limit: int = 500,
        cursor: CommittedCursor | None = None,
    ) -> list[dict[str, Any]]:
        items, _ = self.list_committed_operations_page(limit=limit, cursor=cursor)
        return items

    def list_committed_operations_page(
        self,
        limit: int = 500,
        cursor: CommittedCursor | None = None,
    ) -> tuple[list[dict[str, Any]], CommittedCursor | None]:
        from urllib.parse import quote

        q = f"/operations/committed?limit={limit}"
        if cursor is not None:
            q += (
                f"&after_created_at={quote(cursor.after_created_at)}"
                f"&after_op_id={quote(cursor.after_op_id)}"
            )
        out = self._request("GET", q)
        items = list(out.get("items", []))
        next_c = cursor_from_api_payload(out.get("next_cursor"))
        if next_c is None:
            next_c = next_cursor_from_page(items, limit)
        return items, next_c


def ordered_blob_then_commit(
    journal: DurableJournal,
    token: CommitResult,
    *,
    kind: str,
    path: str,
    payload: dict[str, Any],
    blob_keys: list[str],
    response: dict[str, Any],
    op_id: str | None = None,
) -> str:
    op = op_id or str(uuid.uuid4())
    journal.prepare_operation(
        token, op_id=op, kind=kind, path=path, blob_keys=blob_keys, payload=payload
    )
    return journal.commit_ack(
        token,
        kind=kind,
        path=path,
        blob_keys=blob_keys,
        payload=payload,
        response=response,
        op_id=op,
    )
