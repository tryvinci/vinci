"""Stable cursor pagination for committed operation listing (local + DO journal)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CommittedCursor:
    after_created_at: str
    after_op_id: str


def parse_committed_cursor(
    after_created_at: str | None, after_op_id: str | None
) -> CommittedCursor | None:
    if after_created_at and after_op_id:
        return CommittedCursor(after_created_at=after_created_at, after_op_id=after_op_id)
    return None


def next_cursor_from_page(items: list[dict[str, Any]], limit: int) -> CommittedCursor | None:
    if len(items) < limit or not items:
        return None
    last = items[-1]
    created = str(last.get("created_at") or "")
    op_id = str(last.get("op_id") or "")
    if not created or not op_id:
        return None
    return CommittedCursor(after_created_at=created, after_op_id=op_id)


def cursor_from_api_payload(next_cursor: Any) -> CommittedCursor | None:
    if not isinstance(next_cursor, dict):
        return None
    created = next_cursor.get("after_created_at")
    op_id = next_cursor.get("after_op_id")
    if created and op_id:
        return CommittedCursor(after_created_at=str(created), after_op_id=str(op_id))
    return None
