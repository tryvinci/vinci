"""Fence journal side effects when the writer lease is lost."""

from __future__ import annotations

from typing import Any

from vinci_storage.durable_journal import CommitResult, JournalError


def fence_journal_writer(engine: Any) -> None:
    engine._journal_writer_fenced = True  # noqa: SLF001
    engine._journal_token = None  # noqa: SLF001


def writer_is_fenced(engine: Any) -> bool:
    return bool(getattr(engine, "_journal_writer_fenced", False))


def require_live_writer(engine: Any) -> CommitResult:
    if writer_is_fenced(engine):
        raise JournalError("journal writer fenced")
    token = getattr(engine, "_journal_token", None)
    if token is None:
        raise JournalError("journal writer token missing")
    return token


def assert_journal_writer_live(journal: Any, engine: Any) -> CommitResult:
    """Renew or fence; raises JournalError when lease/token is stale."""
    renew = getattr(engine, "_renew_journal_writer", None)
    if callable(renew):
        renew()
        return require_live_writer(engine)
    token = require_live_writer(engine)
    engine._journal_token = journal.renew_writer(token)  # noqa: SLF001
    return engine._journal_token
