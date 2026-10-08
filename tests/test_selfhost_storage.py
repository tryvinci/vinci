from __future__ import annotations

import hashlib
import io
import json
import os
import sqlite3
import tarfile
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from vinci_runtime.engine import Engine
from vinci_storage.backends import make_cas
from vinci_storage.home_persistence import POINTER_KEY, HomePersistence, PersistenceError
from vinci_storage.r2_client import R2Client


def _expire_pointer_lease(mock_r2: R2Client) -> None:
    head = mock_r2.head(POINTER_KEY)
    assert head is not None
    body = json.loads(head.body.decode("utf-8"))
    body["lease_until"] = (datetime.now(tz=UTC) - timedelta(seconds=30)).isoformat()
    body["released"] = False
    mock_r2.put_json(POINTER_KEY, body)


@pytest.fixture()
def mock_r2(tmp_path: Path) -> R2Client:
    return R2Client(bucket="test", mock_root=tmp_path / "r2")


def test_r2_cas_roundtrip(mock_r2: R2Client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VINCI_CAS_BACKEND", "r2")
    monkeypatch.setenv("VINCI_R2_MOCK_DIR", str(mock_r2.mock_root))
    monkeypatch.setenv("VINCI_R2_BUCKET", "test")
    cas = make_cas(Path("/tmp/unused"))
    digest = cas.put(b"hello-cas")
    assert cas.exists(digest)
    assert cas.get(digest) == b"hello-cas"


def test_home_snapshot_restore(tmp_path: Path, mock_r2: R2Client) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.toml").write_text('demo = true\n', encoding="utf-8")

    p1 = HomePersistence(home, mock_r2, holder_id="holder-a")
    p1.acquire_lock()
    p1.snapshot()
    p1.release_lock()

    home2 = tmp_path / "home2"
    home2.mkdir()
    p2 = HomePersistence(home2, mock_r2, holder_id="holder-b")
    p2.acquire_lock()
    assert p2.restore_if_present() is True
    assert (home2 / "config.toml").read_text(encoding="utf-8") == 'demo = true\n'
    p2.release_lock()


def test_writer_lock_race_only_one_wins(tmp_path: Path, mock_r2: R2Client) -> None:
    home = tmp_path / "home"
    home.mkdir()
    results: list[str] = []

    def worker(name: str) -> None:
        os.environ["VINCI_HOME_LEASE_ACQUIRE_TIMEOUT_SEC"] = "0.2"
        p = HomePersistence(home, mock_r2, holder_id=name)
        try:
            p.acquire_lock()
            results.append(f"ok:{name}")
        except PersistenceError:
            results.append(f"fail:{name}")

    threads = [threading.Thread(target=worker, args=(f"t{i}",)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(1 for r in results if r.startswith("ok:")) == 1


def test_stale_fence_cannot_renew(
    tmp_path: Path, mock_r2: R2Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    a = HomePersistence(home, mock_r2, holder_id="a")
    a.acquire_lock()
    b = HomePersistence(home, mock_r2, holder_id="b")
    monkeypatch.setenv("VINCI_HOME_LEASE_ACQUIRE_TIMEOUT_SEC", "0.05")
    with pytest.raises(PersistenceError):
        b.acquire_lock()
    a.release_lock()
    monkeypatch.setenv("VINCI_HOME_LEASE_ACQUIRE_TIMEOUT_SEC", "5")
    b.acquire_lock()


def test_acquire_waits_for_expired_foreign_lease(
    tmp_path: Path, mock_r2: R2Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VINCI_HOME_LEASE_SECONDS", "1")
    home = tmp_path / "home"
    home.mkdir()
    stale = HomePersistence(home, mock_r2, holder_id="stale")
    stale.acquire_lock()
    waiter = HomePersistence(home, mock_r2, holder_id="waiter")
    monkeypatch.setenv("VINCI_HOME_LEASE_ACQUIRE_TIMEOUT_SEC", "5")
    waiter.acquire_lock()
    waiter.release_lock()


def test_corrupt_snapshot_rejected(tmp_path: Path, mock_r2: R2Client) -> None:
    home = tmp_path / "home"
    home.mkdir()
    mock_r2.put_json("home/snapshot-pointer.json", {"generation": 1, "sha256": "0" * 64})
    mock_r2.put_bytes("home/snapshots/1.tar.gz", b"not-a-tar")
    p = HomePersistence(home, mock_r2)
    p.acquire_lock()
    with pytest.raises(PersistenceError):
        p.restore_if_present()


def test_bridge_auth_blocks_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient
    from vinci_daemon.app import create_app

    monkeypatch.setenv("VINCI_BRIDGE_TOKEN", "bridge-secret")
    monkeypatch.setenv("VINCI_HOME", str(tmp_path / "vinci"))
    eng = Engine(home=tmp_path / "vinci")
    client = TestClient(create_app(engine=eng))
    assert client.get("/healthz").status_code == 200
    assert client.get("/settings").status_code == 401
    authed = client.get("/settings", headers={"Authorization": "Bearer bridge-secret"})
    assert authed.status_code == 200


def test_local_storage_default_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VINCI_CAS_BACKEND", raising=False)
    home = tmp_path / "vinci"
    eng = Engine(home=home)
    from vinci_storage.cas import ContentAddressedStore

    assert isinstance(eng.cas, ContentAddressedStore)
    assert (home / "cas").is_dir()


def test_sqlite_wal_excluded_and_restores(tmp_path: Path, mock_r2: R2Client) -> None:
    home = tmp_path / "home"
    home.mkdir()
    db = home / "vinci.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, v TEXT)")
    conn.execute("INSERT INTO items (v) VALUES ('wal-row')")
    conn.commit()
    conn.close()
    # Simulate active WAL sidecars (may or may not exist on all SQLite builds).
    (home / "vinci.sqlite-wal").write_bytes(b"wal-sidecar-must-not-snapshot")
    (home / "vinci.sqlite-shm").write_bytes(b"shm-sidecar-must-not-snapshot")

    writer = HomePersistence(home, mock_r2, holder_id="wal-writer")
    writer.acquire_lock()
    writer.snapshot()
    writer.release_lock()

    ptr = mock_r2.head("home/snapshot-pointer.json")
    assert ptr is not None
    pointer = json.loads(ptr.body.decode("utf-8"))
    raw = mock_r2.get_bytes(pointer["object_key"])
    assert raw is not None
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        names = tar.getnames()
    assert "vinci.sqlite" in names
    assert not any(n.endswith((".sqlite-wal", ".sqlite-shm")) for n in names)

    home2 = tmp_path / "home2"
    home2.mkdir()
    reader = HomePersistence(home2, mock_r2, holder_id="wal-reader")
    reader.acquire_lock()
    assert reader.restore_if_present() is True
    conn2 = sqlite3.connect(home2 / "vinci.sqlite")
    row = conn2.execute("SELECT v FROM items").fetchone()
    conn2.close()
    assert row == ("wal-row",)
    reader.release_lock()


def test_persistence_unhealthy_when_snapshot_stale(
    tmp_path: Path, mock_r2: R2Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("VINCI_MAX_UNCOMMITTED_SECONDS", "1")
    p = HomePersistence(home, mock_r2)
    p.acquire_lock()
    p.snapshot()
    assert p.healthy is True
    time.sleep(1.2)
    assert p.healthy is False
    monkeypatch.setenv("VINCI_ACCEPT_UNBOUNDED_PERSISTENCE_RISK", "1")
    assert p.healthy is True
    p.release_lock()


def test_snapshot_failure_marks_unhealthy(tmp_path: Path, mock_r2: R2Client) -> None:
    home = tmp_path / "home"
    home.mkdir()

    class FailingClient(R2Client):
        def put_bytes_if_match(self, key: str, data: bytes, **kwargs: object) -> bool:  # noqa: ANN003
            if "snapshots" in key:
                return False
            return super().put_bytes_if_match(key, data, **kwargs)

    failing = FailingClient(bucket=mock_r2.bucket, mock_root=mock_r2.mock_root)
    p = HomePersistence(home, failing, holder_id="fail-writer")
    p.acquire_lock()
    with pytest.raises(PersistenceError):
        p.snapshot()
    assert p.healthy is False


def test_takeover_during_snapshot_blocks_stale_publish(tmp_path: Path, mock_r2: R2Client) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "marker.txt").write_text("a", encoding="utf-8")
    stale = HomePersistence(home, mock_r2, holder_id="stale")
    stale.acquire_lock()
    _expire_pointer_lease(mock_r2)
    intruder = HomePersistence(home, mock_r2, holder_id="intruder")
    intruder.acquire_lock()

    with pytest.raises(PersistenceError):
        stale.snapshot()
    ptr = json.loads(mock_r2.head(POINTER_KEY).body.decode("utf-8"))
    assert ptr["writer_id"] == "intruder"
    assert int(ptr.get("generation", 0)) == 0


def test_release_only_marks_own_pointer_released(tmp_path: Path, mock_r2: R2Client) -> None:
    home = tmp_path / "home"
    home.mkdir()
    a = HomePersistence(home, mock_r2, holder_id="a")
    a.acquire_lock()
    until = (datetime.now(tz=UTC) + timedelta(seconds=120)).isoformat()
    mock_r2.put_json(
        POINTER_KEY,
        {
            "generation": 0,
            "object_key": "",
            "sha256": "",
            "writer_id": "b",
            "fence_token": "b-fence",
            "acquired_at": datetime.now(tz=UTC).isoformat(),
            "lease_until": until,
            "released": False,
        },
    )
    a.release_lock()
    body = json.loads(mock_r2.head(POINTER_KEY).body.decode("utf-8"))
    assert body["writer_id"] == "b"
    assert body.get("released") is not True


def test_clean_restart_acquire_restore_and_snapshot(tmp_path: Path, mock_r2: R2Client) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.toml").write_text("v1\n", encoding="utf-8")
    old = HomePersistence(home, mock_r2, holder_id="process-a")
    old.acquire_lock()
    old.snapshot()
    old.release_lock()

    home2 = tmp_path / "home2"
    home2.mkdir()
    new = HomePersistence(home2, mock_r2, holder_id="process-b")
    new.acquire_lock()
    assert new.restore_if_present() is True
    assert (home2 / "config.toml").read_text(encoding="utf-8") == "v1\n"
    (home2 / "config.toml").write_text("v2\n", encoding="utf-8")
    gen2 = new.snapshot()
    assert gen2 == 2
    ptr = json.loads(mock_r2.head("home/snapshot-pointer.json").body.decode("utf-8"))
    assert ptr["generation"] == 2
    assert ptr["writer_id"] == "process-b"
    new.release_lock()


def test_snapshot_retry_after_failed_pointer_publish(tmp_path: Path, mock_r2: R2Client) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "note.txt").write_text("retry-me", encoding="utf-8")

    class PointerFlaky(R2Client):
        def __init__(self, bucket: str, mock_root: Path) -> None:
            super().__init__(bucket=bucket, mock_root=mock_root)
            self._pointer_puts = 0

        def put_json_if_match(self, key: str, payload: dict, **kwargs: object) -> bool:  # noqa: ANN003
            if (
                key == POINTER_KEY
                and int(payload.get("generation", 0)) > 0
                and payload.get("object_key")
            ):
                self._pointer_puts += 1
                if self._pointer_puts == 1:
                    return False
            return super().put_json_if_match(key, payload, **kwargs)

    flaky = PointerFlaky(bucket=mock_r2.bucket, mock_root=mock_r2.mock_root)
    writer = HomePersistence(home, flaky, holder_id="retry-writer")
    writer.acquire_lock()
    with pytest.raises(PersistenceError):
        writer.snapshot()
    gen = writer.snapshot()
    assert gen == 1
    ptr = json.loads(mock_r2.head("home/snapshot-pointer.json").body.decode("utf-8"))
    assert ptr["generation"] == 1
    assert f".{writer.fence}." in ptr["object_key"]
    assert ptr["object_key"].endswith(".tar.gz")
    writer.release_lock()

    other = HomePersistence(tmp_path / "other", flaky, holder_id="other-writer")
    other.acquire_lock()
    other._generation = 0
    with pytest.raises(PersistenceError):
        other.snapshot()
    other.release_lock()


def test_snapshot_delayed_retry_with_changed_data(tmp_path: Path, mock_r2: R2Client) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "note.txt").write_text("v1", encoding="utf-8")

    class PointerFlaky(R2Client):
        def __init__(self, bucket: str, mock_root: Path) -> None:
            super().__init__(bucket=bucket, mock_root=mock_root)
            self._pointer_puts = 0

        def put_json_if_match(self, key: str, payload: dict, **kwargs: object) -> bool:  # noqa: ANN003
            if (
                key == POINTER_KEY
                and int(payload.get("generation", 0)) > 0
                and payload.get("object_key")
            ):
                self._pointer_puts += 1
                if self._pointer_puts == 1:
                    return False
            return super().put_json_if_match(key, payload, **kwargs)

    flaky = PointerFlaky(bucket=mock_r2.bucket, mock_root=mock_r2.mock_root)
    writer = HomePersistence(home, flaky, holder_id="delay-writer")
    writer.acquire_lock()
    with pytest.raises(PersistenceError):
        writer.snapshot()
    time.sleep(1.1)
    (home / "note.txt").write_text("v2-changed", encoding="utf-8")
    gen = writer.snapshot()
    assert gen == 1
    ptr = json.loads(mock_r2.head("home/snapshot-pointer.json").body.decode("utf-8"))
    assert ptr["sha256"] == hashlib.sha256(mock_r2.get_bytes(ptr["object_key"])).hexdigest()
    writer.release_lock()

    home2 = tmp_path / "home2"
    home2.mkdir()
    reader = HomePersistence(home2, flaky, holder_id="delay-reader")
    reader.acquire_lock()
    assert reader.restore_if_present() is True
    assert (home2 / "note.txt").read_text(encoding="utf-8") == "v2-changed"
    reader.release_lock()


def test_takeover_between_upload_and_pointer_publish_fails(
    tmp_path: Path, mock_r2: R2Client
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "data.txt").write_text("committed", encoding="utf-8")
    first = HomePersistence(home, mock_r2, holder_id="first")
    first.acquire_lock()
    first.snapshot()
    first.release_lock()
    committed = json.loads(mock_r2.head("home/snapshot-pointer.json").body.decode("utf-8"))

    stale = HomePersistence(home, mock_r2, holder_id="stale")
    stale.acquire_lock()
    generation = stale._generation + 1
    data, digest = stale._build_snapshot_archive()
    snap_key = stale._upload_snapshot_object(generation, data, str(uuid.uuid4()))

    ptr_head = mock_r2.head("home/snapshot-pointer.json")
    assert ptr_head is not None
    _expire_pointer_lease(mock_r2)
    intruder = HomePersistence(home, mock_r2, holder_id="intruder")
    intruder.acquire_lock()

    with pytest.raises(PersistenceError, match="stale pointer token"):
        stale._publish_snapshot_pointer(generation, snap_key, digest)

    after = json.loads(mock_r2.head(POINTER_KEY).body.decode("utf-8"))
    assert after["generation"] == committed["generation"]
    assert after["sha256"] == committed["sha256"]
    assert after["object_key"] == committed["object_key"]
    stale.release_lock()


def test_first_snapshot_stale_publish_after_takeover_fails(
    tmp_path: Path, mock_r2: R2Client
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "only.txt").write_text("bootstrap", encoding="utf-8")
    writer = HomePersistence(home, mock_r2, holder_id="first-writer")
    writer.acquire_lock()
    generation = 1
    data, digest = writer._build_snapshot_archive()
    snap_key = writer._upload_snapshot_object(generation, data, str(uuid.uuid4()))
    _expire_pointer_lease(mock_r2)
    intruder = HomePersistence(home, mock_r2, holder_id="intruder")
    intruder.acquire_lock()

    with pytest.raises(PersistenceError):
        writer._publish_snapshot_pointer(generation, snap_key, digest)

    ptr = json.loads(mock_r2.head(POINTER_KEY).body.decode("utf-8"))
    assert int(ptr.get("generation", 0)) == 0
    assert ptr["writer_id"] == "intruder"
    writer.release_lock()
    intruder.release_lock()


def test_stale_writer_cannot_overwrite_existing_snapshot_object(
    tmp_path: Path, mock_r2: R2Client
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    good = HomePersistence(home, mock_r2, holder_id="good")
    good.acquire_lock()
    good.snapshot()
    good.release_lock()

    evil = HomePersistence(home, mock_r2, holder_id="evil")
    evil.acquire_lock()
    evil._generation = 0
    with pytest.raises(PersistenceError):
        evil.snapshot()
    evil.release_lock()


def test_recover_interrupted_jobs(tmp_path: Path) -> None:
    eng = Engine(home=tmp_path)
    eng.init_home(demo=True)
    run_id = "run-interrupted-test"
    eng.store.put_run(run_id, {"skill": "@tryvinci/image-generate"}, "running")
    n = eng.recover_interrupted_jobs()
    assert n >= 1
    updated = eng.store.get_run(run_id)
    assert updated is not None
    assert updated["state"] == "failed"
