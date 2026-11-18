"""SqliteStore under concurrent request threads (COREPRODUC-691).

One connection serves every daemon request thread. Before the store lock, concurrent reads and
writes failed with ``sqlite3.InterfaceError: bad parameter or other API misuse`` (HTTP 500).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from vinci_storage.sqlite_store import SqliteStore


def test_concurrent_reads_and_writes_do_not_fail(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "vinci.sqlite")

    def work(n: int) -> int:
        for i in range(40):
            store.put_run(f"run-{n}-{i}", {"inputs": {"n": n}}, "completed")
            assert store.get_run(f"run-{n}-{i}") is not None
            store.list_runs()
        return n

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sorted(pool.map(work, range(8))) == list(range(8))
    assert len(store.list_runs()) == 8 * 40
