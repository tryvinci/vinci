"""Single-tenant home snapshot persistence to R2 (pointer is the only writer authority)."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import shutil
import tarfile
import tempfile
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, NoReturn

from vinci_storage.r2_client import R2Client
from vinci_storage.sqlite_backup import backup_sqlite_file

LOG = logging.getLogger("vinci.home_persistence")

POINTER_KEY = "home/snapshot-pointer.json"
SNAPSHOT_PREFIX = "home/snapshots"


class PersistenceError(RuntimeError):
    pass


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _is_sqlite_sidecar(path: Path) -> bool:
    name = path.name
    if name.endswith((".sqlite-wal", ".sqlite-shm", ".sqlite-journal")):
        return True
    return name.endswith(("-wal", "-shm", "-journal")) and ".sqlite" in name


def _normalize_pointer(raw: dict[str, Any]) -> dict[str, Any]:
    """Map legacy pointer fields to the unified authority schema."""
    out = dict(raw)
    if "writer_id" not in out and "writer_holder" in out:
        out["writer_id"] = out["writer_holder"]
    if "fence_token" not in out and "writer_fence" in out:
        out["fence_token"] = out["writer_fence"]
    if "fence_token" not in out and "fence" in out:
        out["fence_token"] = out["fence"]
    if "lease_until" not in out and "until" in out:
        out["lease_until"] = out["until"]
    if "released" not in out:
        out["released"] = False
    return out


class HomePersistence:
    def __init__(self, home: Path, client: R2Client, holder_id: str | None = None) -> None:
        self.home = home
        self.client = client
        self.holder_id = holder_id or str(uuid.uuid4())
        self.fence = str(uuid.uuid4())
        self._lease_seconds = int(os.environ.get("VINCI_HOME_LEASE_SECONDS", "120"))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._pointer_etag: str | None = None
        self._snapshot_lock = threading.Lock()
        self._healthy = True
        self._last_error: str | None = None
        self._generation = 0
        self._last_snapshot_monotonic = time.monotonic()
        self._snapshot_interval = int(os.environ.get("VINCI_HOME_SNAPSHOT_SECONDS", "60"))
        self._max_uncommitted = int(
            os.environ.get(
                "VINCI_MAX_UNCOMMITTED_SECONDS",
                str(max(120, self._snapshot_interval * 2)),
            )
        )

    @property
    def healthy(self) -> bool:
        if not self._healthy:
            return False
        if os.environ.get("VINCI_ACCEPT_UNBOUNDED_PERSISTENCE_RISK", "") == "1":
            return True
        age = time.monotonic() - self._last_snapshot_monotonic
        return age <= float(self._max_uncommitted)

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def seconds_since_snapshot(self) -> float:
        return time.monotonic() - self._last_snapshot_monotonic

    def _fail(self, message: str) -> NoReturn:
        self._healthy = False
        self._last_error = message
        LOG.error("%s", message)
        raise PersistenceError(message)

    def _lease_until_iso(self) -> str:
        return (datetime.now(tz=UTC) + timedelta(seconds=self._lease_seconds)).isoformat()

    def _bootstrap_pointer_body(self) -> dict[str, Any]:
        return {
            "generation": 0,
            "object_key": "",
            "sha256": "",
            "writer_id": self.holder_id,
            "fence_token": self.fence,
            "acquired_at": _now_iso(),
            "lease_until": self._lease_until_iso(),
            "released": False,
        }

    def _claim_pointer_body(self, current: dict[str, Any]) -> dict[str, Any]:
        body = _normalize_pointer(current)
        body["writer_id"] = self.holder_id
        body["fence_token"] = self.fence
        body["acquired_at"] = _now_iso()
        body["lease_until"] = self._lease_until_iso()
        body["released"] = False
        return body

    def _lease_active(self, pointer: dict[str, Any]) -> bool:
        p = _normalize_pointer(pointer)
        if p.get("released") is True:
            return False
        until = p.get("lease_until")
        if not isinstance(until, str):
            return False
        try:
            return _parse_iso(until) > datetime.now(tz=UTC)
        except ValueError:
            return False

    def _owns_pointer(self, pointer: dict[str, Any]) -> bool:
        p = _normalize_pointer(pointer)
        return p.get("writer_id") == self.holder_id and p.get("fence_token") == self.fence

    def _read_pointer_head(self) -> tuple[dict[str, Any] | None, str | None]:
        head = self.client.head(POINTER_KEY)
        if head is None:
            return None, None
        return _normalize_pointer(json.loads(head.body.decode("utf-8"))), head.etag

    def _commit_pointer_cas(self, body: dict[str, Any], expected_etag: str | None) -> bool:
        ok = self.client.put_json_if_match(
            POINTER_KEY,
            body,
            if_match=expected_etag,
            if_none_match=expected_etag is None,
        )
        if not ok:
            return False
        head = self.client.head(POINTER_KEY)
        if head is None:
            self._fail("pointer disappeared after CAS")
        self._pointer_etag = head.etag
        return True

    def _assert_owned_token(self) -> dict[str, Any]:
        if self._pointer_etag is None:
            self._fail("writer not acquired")
        pointer, etag = self._read_pointer_head()
        if pointer is None or etag is None:
            self._fail("pointer missing during operation")
        if etag != self._pointer_etag:
            self._fail("stale pointer token (concurrent takeover)")
        if not self._owns_pointer(pointer):
            self._fail("lost pointer writer authority")
        if not self._lease_active(pointer):
            self._fail("writer lease expired")
        return pointer

    def _pointer_object_key(self, pointer: dict[str, Any]) -> str:
        generation = int(pointer["generation"])
        custom = pointer.get("object_key")
        if isinstance(custom, str) and custom:
            return custom
        return f"{SNAPSHOT_PREFIX}/{generation}.tar.gz"

    def _snapshot_object_key(self, generation: int, attempt: str) -> str:
        return f"{SNAPSHOT_PREFIX}/{generation}.{self.fence}.{attempt}.tar.gz"

    def _upload_snapshot_object(self, generation: int, data: bytes, attempt: str) -> str:
        snap_key = self._snapshot_object_key(generation, attempt)
        uploaded = self.client.put_bytes_if_match(
            snap_key,
            data,
            if_match=None,
            if_none_match=True,
            content_type="application/gzip",
        )
        if not uploaded:
            self._fail("snapshot object already exists for attempt id")
        return snap_key

    def _publish_snapshot_pointer(self, generation: int, snap_key: str, digest: str) -> None:
        self.renew_lock()
        current = self._assert_owned_token()
        if int(current.get("generation", 0)) >= generation:
            self._fail("refusing to publish stale snapshot generation")
        body = dict(current)
        body.update(
            {
                "generation": generation,
                "object_key": snap_key,
                "sha256": digest,
                "lease_until": self._lease_until_iso(),
                "released": False,
            }
        )
        if not self._commit_pointer_cas(body, self._pointer_etag):
            self._fail("failed to publish snapshot pointer atomically")

    def _build_snapshot_archive(self) -> tuple[bytes, str]:
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp)
            for name in ("vinci.sqlite", "index.sqlite"):
                backup_sqlite_file(self.home / name, stage / name)
            for rel in _home_members(self.home):
                src = self.home / rel
                if src.is_file():
                    dest = stage / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest)
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w:gz") as tar:
                for path in stage.rglob("*"):
                    if path.is_file():
                        tar.add(path, arcname=path.relative_to(stage).as_posix())
            data = buf.getvalue()
        return data, hashlib.sha256(data).hexdigest()

    def acquire_lock(self) -> None:
        timeout = float(os.environ.get("VINCI_HOME_LEASE_ACQUIRE_TIMEOUT_SEC", "150"))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            pointer, etag = self._read_pointer_head()
            if pointer is None:
                body = self._bootstrap_pointer_body()
                if self._commit_pointer_cas(body, None):
                    self._generation = 0
                    return
                continue
            if self._lease_active(pointer):
                if self._owns_pointer(pointer):
                    self._pointer_etag = etag
                    self._generation = int(pointer.get("generation", 0))
                    return
                until_raw = pointer.get("lease_until")
                if until_raw:
                    remaining = (
                        _parse_iso(str(until_raw)) - datetime.now(tz=UTC)
                    ).total_seconds()
                    time.sleep(min(2.0, max(0.05, remaining + 0.05)))
                else:
                    time.sleep(0.5)
                continue
            body = self._claim_pointer_body(pointer)
            if self._commit_pointer_cas(body, etag):
                self._generation = int(pointer.get("generation", 0))
                return
        self._fail("failed to acquire home writer lease")

    def renew_lock(self) -> None:
        if self._pointer_etag is None:
            self.acquire_lock()
            return
        current = self._assert_owned_token()
        body = dict(current)
        body["lease_until"] = self._lease_until_iso()
        body["released"] = False
        if not self._commit_pointer_cas(body, self._pointer_etag):
            self._fail("lost home writer lease (fence expired or stolen)")

    def release_lock(self) -> None:
        if self._pointer_etag is None:
            return
        pointer, etag = self._read_pointer_head()
        if pointer is None or etag is None:
            self._pointer_etag = None
            return
        if etag != self._pointer_etag:
            self._pointer_etag = None
            return
        if self._owns_pointer(pointer):
            body = dict(pointer)
            body["released"] = True
            self._commit_pointer_cas(body, self._pointer_etag)
        self._pointer_etag = None

    def restore_if_present(self) -> bool:
        pointer_head = self.client.head(POINTER_KEY)
        if pointer_head is None:
            legacy = self.client.get_bytes("home/snapshot.tar.gz")
            if legacy is None:
                return False
            return self._extract_snapshot(legacy, expected_sha256=None)

        pointer = _normalize_pointer(json.loads(pointer_head.body.decode("utf-8")))
        generation = int(pointer.get("generation", 0))
        if generation < 1:
            return False
        sha = str(pointer.get("sha256", ""))
        key = self._pointer_object_key(pointer)
        if not sha or not key:
            return False
        raw = self.client.get_bytes(key)
        if raw is None:
            self._fail(f"missing snapshot object {key}")
        if hashlib.sha256(raw).hexdigest() != sha:
            self._fail("snapshot sha256 mismatch")
        ok = self._extract_snapshot(raw, expected_sha256=sha)
        self._generation = generation
        return ok

    def _extract_snapshot(self, raw: bytes, expected_sha256: str | None) -> bool:
        if expected_sha256 and hashlib.sha256(raw).hexdigest() != expected_sha256:
            self._fail("corrupt snapshot archive")
        self.home.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
            tar.extractall(self.home, filter="data")
        return True

    def snapshot(self) -> int:
        self.renew_lock()
        with self._snapshot_lock:
            generation = self._generation + 1
            attempt = str(uuid.uuid4())
            data, digest = self._build_snapshot_archive()
            self.renew_lock()
            snap_key = self._upload_snapshot_object(generation, data, attempt)
            self._publish_snapshot_pointer(generation, snap_key, digest)
            self._generation = generation
            self._last_snapshot_monotonic = time.monotonic()
            return generation

    def start_background(self, interval: int | None = None) -> None:
        every = interval or self._snapshot_interval

        def _loop() -> None:
            while not self._stop.wait(every):
                try:
                    self.snapshot()
                except Exception as exc:  # noqa: BLE001
                    self._healthy = False
                    self._last_error = str(exc)
                    LOG.exception("home snapshot failed")
                    return

        self._thread = threading.Thread(target=_loop, name="vinci-home-snapshot", daemon=True)
        self._thread.start()

    def stop(self, join_seconds: float | None = None) -> None:
        self._stop.set()
        timeout = join_seconds or float(os.environ.get("VINCI_HOME_STOP_JOIN_SECONDS", "150"))
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        try:
            self.snapshot()
        except Exception as exc:  # noqa: BLE001
            LOG.exception("final snapshot failed: %s", exc)
        finally:
            self.release_lock()


def _home_members(home: Path) -> list[str]:
    skip_dirs = {"cas", "snapshots"}
    out: list[str] = []
    for path in home.rglob("*"):
        if not path.is_file():
            continue
        if _is_sqlite_sidecar(path):
            continue
        rel = path.relative_to(home)
        if rel.parts and rel.parts[0] in skip_dirs:
            continue
        if rel.name in {"vinci.sqlite", "index.sqlite"}:
            continue
        out.append(str(rel))
    return out


def persistence_from_env(home: Path) -> HomePersistence | None:
    client = R2Client.from_env()
    if client is None:
        return None
    return HomePersistence(home, client)
