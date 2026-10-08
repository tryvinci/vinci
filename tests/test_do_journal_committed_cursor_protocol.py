from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from vinci_storage.committed_cursor import next_cursor_from_page
from vinci_storage.durable_journal import DoJournalClient, JournalError


def _page_rows(
    rows: list[dict[str, Any]],
    limit: int,
    after_created: str | None,
    after_op: str | None,
) -> list[dict[str, Any]]:
    committed = [r for r in rows if r.get("status") == "committed"]
    committed.sort(key=lambda r: (str(r["created_at"]), str(r["op_id"])))
    if after_created and after_op:
        committed = [
            r
            for r in committed
            if r["created_at"] > after_created
            or (r["created_at"] == after_created and r["op_id"] > after_op)
        ]
    return committed[:limit]


class _MockDoJournalHandler(BaseHTTPRequestHandler):
    rows: list[dict[str, Any]] = []

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length) if length else b""
        return json.loads(raw.decode("utf-8")) if raw else {}

    def _send(self, status: int, body: dict[str, Any]) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/operations/committed":
            self._send(404, {"error": "not_found"})
            return
        qs = parse_qs(parsed.query)
        if "offset" in qs:
            self._send(
                400,
                {
                    "error": "offset_unsupported_use_cursor",
                    "detail": "after_created_at + after_op_id",
                },
            )
            return
        limit = min(500, max(1, int((qs.get("limit") or ["500"])[0])))
        after_created = (qs.get("after_created_at") or [None])[0]
        after_op = (qs.get("after_op_id") or [None])[0]
        items = _page_rows(self.rows, limit, after_created, after_op)
        nc = next_cursor_from_page(items, limit)
        next_cursor = (
            {"after_created_at": nc.after_created_at, "after_op_id": nc.after_op_id}
            if nc
            else None
        )
        self._send(200, {"items": items, "next_cursor": next_cursor})


@pytest.fixture()
def mock_do_base_url() -> str:
    total = 10_050
    rows = [
        {
            "op_id": f"do-op-{i:05d}",
            "created_at": f"2026-02-01T12:00:00.{i:06d}Z",
            "status": "committed",
            "kind": "settings",
        }
        for i in range(total)
    ]
    _MockDoJournalHandler.rows = rows
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MockDoJournalHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    base = f"http://{host}:{port}"
    yield base
    server.shutdown()


def test_do_client_rejects_offset_on_mock(
    mock_do_base_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VINCI_BRIDGE_TOKEN", "b" * 16)
    client = DoJournalClient(mock_do_base_url)
    with pytest.raises(JournalError):
        client._request("GET", "/operations/committed?limit=10&offset=500")


def test_do_client_iterates_more_than_ten_thousand_via_api_cursor(
    mock_do_base_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VINCI_BRIDGE_TOKEN", "b" * 16)
    client = DoJournalClient(mock_do_base_url)
    seen: list[str] = []
    for row in client.iter_committed_operations(page_size=500):
        seen.append(str(row["op_id"]))
    assert len(seen) == 10_050
    assert seen[0] == "do-op-00000"
    assert seen[-1] == "do-op-10049"
    assert len(set(seen)) == 10_050
