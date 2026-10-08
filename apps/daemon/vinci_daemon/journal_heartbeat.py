"""Background writer lease renewal (compute/idle longer than request scope)."""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

from vinci_storage.durable_journal import CommitResult, DurableJournal, JournalError

from vinci_daemon.journal_fencing import fence_journal_writer

LOG = logging.getLogger("vinci.journal_heartbeat")


class JournalWriterHeartbeat:
    def __init__(self, journal: DurableJournal, token: CommitResult, engine: Any) -> None:
        self._journal = journal
        self._token = token
        self._engine = engine
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._fenced = False

    def start(self) -> None:
        lease = max(1, int(os.environ.get("VINCI_HOME_LEASE_SECONDS", "120")))
        interval = max(1, lease // 3)
        self._thread = threading.Thread(
            target=self._loop,
            args=(interval,),
            name="vinci-journal-heartbeat",
            daemon=True,
        )
        self._thread.start()

    def _fence(self) -> None:
        if self._fenced:
            return
        self._fenced = True
        self._stop.set()
        fence_journal_writer(self._engine)
        LOG.warning("journal writer fenced after heartbeat renew failure")

    def _loop(self, interval: float) -> None:
        while not self._stop.wait(interval):
            try:
                self.renew_now()
            except JournalError as exc:
                LOG.warning("journal heartbeat renew failed: %s", exc)
                break

    def renew_now(self) -> None:
        if self._fenced or getattr(self._engine, "_journal_writer_fenced", False):
            raise JournalError("journal writer fenced")
        try:
            self._token = self._journal.renew_writer(self._token)
            self._engine._journal_token = self._token  # noqa: SLF001
        except JournalError:
            self._fence()
            raise

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    @property
    def token(self) -> CommitResult:
        return self._token

    @property
    def fenced(self) -> bool:
        return self._fenced


def attach_heartbeat(engine: Any, heartbeat: JournalWriterHeartbeat) -> None:
    engine._journal_heartbeat = heartbeat  # noqa: SLF001
    engine._renew_journal_writer = heartbeat.renew_now  # noqa: SLF001
