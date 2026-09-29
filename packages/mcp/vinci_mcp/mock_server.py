"""Loopback MCP stub: catalog + PNG/MP4 generate at $0. No live provider spend."""

from __future__ import annotations

import argparse
import base64
import json
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from vinci_provider_sdk.mock import MP4_SWATCH, PNG_SWATCH

MOCK_PNG_MODEL: dict[str, Any] = {
    "id": "mcp:png:v1",
    "display_name": "MCP PNG",
    "provider": "mcp",
    "capabilities": ["t2i"],
    "pricing": {
        "unit": "image",
        "amount": 0.0,
        "currency": "USD",
        "snapshot_at": datetime(2026, 8, 27, tzinfo=UTC).isoformat(),
    },
    "secret_names": ["MCP_API_KEY"],
}

MOCK_MP4_MODEL: dict[str, Any] = {
    "id": "mcp:mp4:v1",
    "display_name": "MCP MP4",
    "provider": "mcp",
    "capabilities": ["t2v"],
    "pricing": {
        "unit": "video",
        "amount": 0.0,
        "currency": "USD",
        "snapshot_at": datetime(2026, 8, 27, tzinfo=UTC).isoformat(),
    },
    "secret_names": ["MCP_API_KEY"],
}


def handle_rpc(body: dict[str, Any]) -> dict[str, Any]:
    rpc_id = body.get("id")
    method = body.get("method")
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {
                "tools": [
                    {"name": "vinci.models_list", "description": "List catalog models."},
                    {"name": "vinci.image_generate", "description": "Return a $0 PNG swatch."},
                    {"name": "vinci.video_generate", "description": "Return a $0 MP4 swatch."},
                ]
            },
        }
    if method == "tools/call":
        params = body.get("params") or {}
        name = params.get("name") if isinstance(params, dict) else None
        if name == "vinci.models_list":
            listed: dict[str, Any] = {"models": [MOCK_PNG_MODEL, MOCK_MP4_MODEL]}
            return _tool_text(rpc_id, listed)
        if name == "vinci.image_generate":
            image: dict[str, Any] = {
                "mime": "image/png",
                "b64": base64.b64encode(PNG_SWATCH).decode("ascii"),
                "model_id": "mcp:png:v1",
            }
            return _tool_text(rpc_id, image)
        if name == "vinci.video_generate":
            video: dict[str, Any] = {
                "mime": "video/mp4",
                "b64": base64.b64encode(MP4_SWATCH).decode("ascii"),
                "model_id": "mcp:mp4:v1",
            }
            return _tool_text(rpc_id, video)
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {"code": -32601, "message": f"unknown tool {name}"},
        }
    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "error": {"code": -32601, "message": f"unknown method {method}"},
    }


def _tool_text(rpc_id: object, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "result": {"content": [{"type": "text", "text": json.dumps(payload)}]},
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/healthz":
            self._send(200, {"status": "ok"})
            return
        self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path != "/mcp":
            self._send(404, {"error": "not found"})
            return
        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._send(400, {"error": "invalid json"})
            return
        if not isinstance(body, dict):
            self._send(400, {"error": "invalid json"})
            return
        self._send(200, handle_rpc(body))

    def _send(self, code: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    parser = argparse.ArgumentParser(description="Loopback Vinci MCP stub ($0 PNG/MP4).")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=14311)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
