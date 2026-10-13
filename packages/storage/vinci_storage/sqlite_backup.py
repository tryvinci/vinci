from __future__ import annotations

import sqlite3
from pathlib import Path


def backup_sqlite_file(source: Path, destination: Path) -> None:
    """Consistent SQLite copy via the backup API (safe under concurrent readers)."""
    if not source.is_file():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    dst = sqlite3.connect(destination)
    try:
        src.backup(dst)
        dst.commit()
    finally:
        src.close()
        dst.close()
