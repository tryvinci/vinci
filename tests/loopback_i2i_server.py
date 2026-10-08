"""Minimal loopback I2I server for submit-window gate tests."""

from __future__ import annotations

import json
import os
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


class _LoopbackState:
    submit_count = 0
    status_poll_count = 0
    jobs: dict[str, dict[str, Any]] = {}
    lock = threading.Lock()


def _bump_counter(path: str | None) -> None:
    if not path:
        return
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    n = int(p.read_text(encoding="utf-8").strip() or "0") if p.is_file() else 0
    p.write_text(str(n + 1), encoding="utf-8")


class LoopbackI2IHandler(BaseHTTPRequestHandler):
    state = _LoopbackState
    output_digest: str = ""

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/submit":
            self.send_error(404)
            return
        body = self._read_json()
        with self.state.lock:
            self.state.submit_count += 1
            _bump_counter(os.environ.get("VINCI_TEST_LOOPBACK_SUBMIT_COUNTER_PATH"))
            ref = uuid.uuid4().hex
            self.state.jobs[ref] = {
                "polls": 0,
                "request_id": str(body.get("idempotency_key") or ref),
                "payload": body,
            }
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(
            json.dumps({"ref": ref, "request_id": body.get("idempotency_key")}).encode("utf-8")
        )

    def do_GET(self) -> None:  # noqa: N802
        if not self.path.startswith("/v1/status/"):
            self.send_error(404)
            return
        ref = self.path.split("/v1/status/", 1)[1]
        delay_ms = os.environ.get("VINCI_TEST_LOOPBACK_STATUS_DELAY_MS")
        if delay_ms:
            import time

            time.sleep(int(delay_ms) / 1000.0)
        with self.state.lock:
            job = self.state.jobs.get(ref)
            if job is None:
                self.send_error(404)
                return
            job["polls"] += 1
            self.state.status_poll_count += 1
            polls = job["polls"]
        # Complete on second poll so _wait_status exercises polling.
        if polls < 2:
            payload = {"state": "running", "outputs": [], "progress": 0.5}
        else:
            digest = self.output_digest or os.environ.get(
                "VINCI_TEST_LOOPBACK_OUTPUT_DIGEST", ""
            )
            if not digest:
                raise RuntimeError("loopback output digest not configured")
            payload = {"state": "completed", "outputs": [digest], "progress": 1.0}
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode("utf-8"))


def start_loopback_i2i_server() -> tuple[ThreadingHTTPServer, threading.Thread, int]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), LoopbackI2IHandler)
    port = int(server.server_address[1])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, port


def reset_loopback_state() -> None:
    with _LoopbackState.lock:
        _LoopbackState.submit_count = 0
        _LoopbackState.status_poll_count = 0
        _LoopbackState.jobs.clear()
