#!/usr/bin/env python3
"""Refresh ``vinci_mcp/catalogs/<provider>.json``: every Higgsfield and Magnific model, priced.

Free and read-only: it calls each provider's model list and its price preview (Higgsfield
``estimate_video_cost`` / ``estimate_image_cost``, Magnific ``simulate_cost``), never a generate
tool. The sign-in is a throwaway: the token stays in memory and is revoked at the end
(COREPRODUC-669).

Usage:
    python scripts/refresh_connector_catalogs.py [mcp_higgsfield] [mcp_magnific]

It prints one sign-in link per provider; open each in a browser signed in to that provider. The
loopback callback (http://127.0.0.1:47613/callback) finishes the sign-in.
"""

from __future__ import annotations

import http.server
import logging
import sys
import threading
import time
import urllib.parse
from typing import Any

from vinci_mcp import oauth
from vinci_mcp.catalog_live import refresh
from vinci_mcp.connectors import connector_for

PORT = 47613
REDIRECT = f"http://127.0.0.1:{PORT}/callback"
CODES: dict[str, dict[str, str]] = {}


class Memory:
    """Credentials in memory only: nothing reaches the keychain or a file."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def resolve(self, name: str) -> str | None:
        return self.data.get(name)

    def put(self, name: str, value: str) -> str:
        self.data[name] = value
        return "memory"

    def delete(self, name: str) -> None:
        self.data.pop(name, None)


class Callback(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 — http.server's name
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
        CODES[query.get("state", "")] = query
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Signed in. You can close this tab.")

    def log_message(self, *args: Any) -> None:
        pass


ALLOWED = {
    "models_explore",
    "images_models_list",
    "video_models_list",
    "simulate_cost",
    "estimate_image_cost",
    "estimate_video_cost",
}  # previews only: no generate tool, so the refresh never spends


def run(provider_id: str, store: Memory) -> dict[str, Any]:
    """List and price one provider's models; each call takes a fresh token (a run outlives one)."""
    from vinci_mcp.adapter import HttpMcpTransport

    connector = connector_for(provider_id)
    assert connector is not None
    transport = HttpMcpTransport(
        connector.url, timeout=120, token_provider=lambda: oauth.access_token(store, provider_id)
    )

    def call(name: str, arguments: dict[str, Any]) -> Any:
        if name not in ALLOWED:
            raise RuntimeError(f"refresh does not call {name}")
        return transport.call("tools/call", {"name": name, "arguments": arguments})

    return refresh(connector, call)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    providers = sys.argv[1:] or ["mcp_higgsfield", "mcp_magnific"]
    server = http.server.HTTPServer(("127.0.0.1", PORT), Callback)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    store = Memory()
    states = {}
    for provider_id in providers:
        connector = connector_for(provider_id)
        assert connector is not None, provider_id
        started = oauth.start(store, provider_id, connector.url, REDIRECT)
        states[provider_id] = dict(
            urllib.parse.parse_qsl(urllib.parse.urlparse(started["authorize_url"]).query)
        )["state"]
        print(f"Sign in to {connector.label}: {started['authorize_url']}", flush=True)
    # Each code is exchanged the moment it comes back: a code waits minutes at most (a Magnific
    # code had expired after the 20-minute Higgsfield run, 2026-11-16).
    deadline, signed = time.time() + 600, []
    while len(signed) < len(states) and time.time() < deadline:
        for provider_id, state in states.items():
            if provider_id not in signed and state in CODES:
                query = CODES[state]
                oauth.finish(
                    store, code=query.get("code", ""), state=state, error=query.get("error", "")
                )
                signed.append(provider_id)
        time.sleep(1)
    try:
        for provider_id in signed:
            snapshot = run(provider_id, store)
            print(f"{provider_id}: {len(snapshot['rows'])} rows written", flush=True)
    finally:
        for provider_id in signed:
            oauth.disconnect(store, provider_id)  # revoke the throwaway sign-in
    server.shutdown()


if __name__ == "__main__":
    main()
