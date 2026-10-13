"""Exclusive daemon lock per VINCI_HOME (local SQLite/CAS safety)."""

from __future__ import annotations

import fcntl
import os
from pathlib import Path

_LOCK_FD: int | None = None


def acquire_home_daemon_lock(home: Path) -> None:
    global _LOCK_FD
    if os.environ.get("VINCI_SKIP_HOME_LOCK", "") == "1":
        return
    home.mkdir(parents=True, exist_ok=True)
    lock_path = home / ".daemon.lock"
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise SystemExit(
            "another Vinci daemon already holds this VINCI_HOME; stop the other daemon first"
        ) from None
    _LOCK_FD = fd


def release_home_daemon_lock() -> None:
    global _LOCK_FD
    if _LOCK_FD is None:
        return
    try:
        fcntl.flock(_LOCK_FD, fcntl.LOCK_UN)
    finally:
        os.close(_LOCK_FD)
        _LOCK_FD = None
