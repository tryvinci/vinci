"""A sign-in submit opens one MCP session and lists the tools once (COREPRODUC-800).

A local fake streamable-HTTP server (FastMCP) counts sessions and calls. No provider, no spend.
No ``from __future__ import annotations``: FastMCP 1.12 (the hosted pin) reads tool annotations.
"""

import asyncio
import socket
import threading
import time
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import uvicorn
import vinci_mcp.adapter as adapter
from mcp.server.fastmcp import FastMCP
from vinci_mcp.adapter import HttpMcpTransport, McpProvider
from vinci_protocol.models import JobRequest
from vinci_storage.cas import ContentAddressedStore

REQ = JobRequest(
    capability="t2i",
    model_id="mcp_higgsfield:soul_2",
    inputs={"prompt": "a lamp"},
    idempotency_key="run-1:node-1",
)


@pytest.fixture
def fake_higgsfield(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[str, Counter[str]]]:
    """A fake Higgsfield MCP server; yields its URL and the counts of sessions and MCP calls."""
    counts: Counter[str] = Counter()
    fake = FastMCP("fake-higgsfield")

    @fake.tool()
    def estimate_image_cost(params: dict) -> dict:
        return {"cost": {"credits": 1}}

    @fake.tool()
    def generate_image(params: dict) -> dict:
        return {"results": [{"id": "job-1", "status": "queued"}]}

    inner = fake.streamable_http_app()

    async def app(scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            return await inner(scope, receive, send)
        first = await receive()
        body = first.get("body", b"").replace(b" ", b"")
        counts["sessions"] += b'"method":"initialize"' in body
        counts["calls"] += b'"method":"tools/' in body
        sent = False

        async def again() -> Any:
            nonlocal sent
            if not sent:
                sent = True
                return first
            return await receive()

        return await inner(scope, again, send)

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    # The SDK session path, as for a remote provider; the fake server bills nothing.
    monkeypatch.setattr(adapter, "_LOOPBACK_HOSTS", set())
    monkeypatch.setenv("VINCI_ALLOW_LIVE_SPEND", "1")
    yield f"http://127.0.0.1:{port}/mcp", counts
    server.should_exit = True


def _plugin(url: str, tmp_path: Path) -> McpProvider:
    transport = HttpMcpTransport(url, timeout=10, token_provider=lambda: "fake-token")
    return McpProvider(
        transport, cas=ContentAddressedStore(tmp_path / "cas"), provider_id="mcp_higgsfield"
    )


def test_an_estimate_and_its_submit_share_one_session(
    fake_higgsfield: tuple[str, Counter[str]], tmp_path: Path
) -> None:
    """As the hosted backend runs it: 1 session, 3 calls (was 4 sessions, 6 calls)."""
    url, counts = fake_higgsfield
    plugin = _plugin(url, tmp_path)
    with plugin.session():
        plugin.estimate(REQ)
        assert plugin.submit(REQ).ref == "job-1"
    assert counts == Counter(sessions=1, calls=3)  # tools/list, price preview, generate


def test_a_submit_alone_lists_the_tools_once_and_works_in_a_running_loop(
    fake_higgsfield: tuple[str, Counter[str]], tmp_path: Path
) -> None:
    """The daemon path (no outer block): the estimate's session, then one for the submit."""
    url, counts = fake_higgsfield
    plugin = _plugin(url, tmp_path)

    async def in_loop() -> str:  # a caller inside a running event loop
        plugin.estimate(REQ)
        return plugin.submit(REQ).ref

    assert asyncio.run(in_loop()) == "job-1"
    # The submit reuses the estimate's names; its session lists once more for the SDK's result
    # check (was 4 sessions, 6 calls).
    assert counts == Counter(sessions=2, calls=4)


def test_a_session_that_does_not_open_falls_back_to_one_per_call(
    fake_higgsfield: tuple[str, Counter[str]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url, counts = fake_higgsfield

    async def refuse(self: HttpMcpTransport, ready: Any) -> None:
        ready.set_exception(ConnectionError("no session"))

    monkeypatch.setattr(HttpMcpTransport, "_serve", refuse)
    plugin = _plugin(url, tmp_path)
    with plugin.session():
        plugin.estimate(REQ)
        assert plugin.submit(REQ).ref == "job-1"
    assert counts["sessions"] == 3  # tools/list once, then the preview and the generate


def test_the_tool_list_is_reused_for_a_minute_and_a_failure_is_not_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lists: list[int] = []

    class Transport:
        fail = True

        def call(self, method: str, params: dict) -> dict:
            assert method == "tools/list"
            lists.append(1)
            if self.fail:
                raise ConnectionError("down")
            return {"tools": [{"name": "generate_image"}]}

    transport = Transport()
    plugin = McpProvider(transport, provider_id="mcp_higgsfield")  # type: ignore[arg-type]
    assert plugin.catalog()  # the mapping, as before
    transport.fail = False
    plugin.catalog()
    plugin.catalog()
    assert len(lists) == 2  # the failure asked again; the answer is reused
    now = time.monotonic()
    monkeypatch.setattr(adapter.time, "monotonic", lambda: now + adapter._TOOLS_TTL_S + 1)
    plugin.catalog()
    assert len(lists) == 3  # stale after the TTL: a removed tool leaves the rows
