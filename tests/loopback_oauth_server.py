"""Loopback OAuth authorization server for connector tests. No live providers."""

from __future__ import annotations

import base64
import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse


class OAuthServer:
    def __init__(self) -> None:
        self.codes: dict[str, str] = {}
        self.revoked: list[str] = []
        self._seq = 0
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        if self._httpd is None:
            raise RuntimeError("server is not running")
        return int(self._httpd.server_address[1])

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: object) -> None:
                del fmt, args

            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                if parsed.path == "/.well-known/oauth-protected-resource":
                    self._json(
                        {
                            "resource": owner.origin + "/mcp",
                            "authorization_servers": [owner.origin],
                        }
                    )
                    return
                if parsed.path == "/.well-known/oauth-authorization-server":
                    self._json(
                        {
                            "issuer": owner.origin,
                            "authorization_endpoint": owner.origin + "/authorize",
                            "token_endpoint": owner.origin + "/token",
                            "registration_endpoint": owner.origin + "/register",
                            "revocation_endpoint": owner.origin + "/revoke",
                            "response_types_supported": ["code"],
                            "grant_types_supported": ["authorization_code", "refresh_token"],
                            "code_challenge_methods_supported": ["S256"],
                            "token_endpoint_auth_methods_supported": ["none"],
                            "scopes_supported": ["openid", "offline_access"],
                        }
                    )
                    return
                if parsed.path == "/authorize":
                    query = parse_qs(parsed.query)
                    owner._seq += 1
                    code = f"code-{owner._seq}"
                    challenge = query.get("code_challenge", [""])[0]
                    method = query.get("code_challenge_method", [""])[0]
                    if method != "S256" or not challenge:
                        self.send_error(400)
                        return
                    owner.codes[code] = challenge
                    target = query.get("redirect_uri", [""])[0]
                    state = query.get("state", [""])[0]
                    location = target + ("&" if "?" in target else "?") + urlencode(
                        {"code": code, "state": state}
                    )
                    self.send_response(302)
                    self.send_header("Location", location)
                    self.end_headers()
                    return
                self.send_error(404)

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("content-length") or "0")
                raw = self.rfile.read(length).decode("utf-8")
                parsed = urlparse(self.path)
                if parsed.path == "/register":
                    body = json.loads(raw or "{}")
                    owner._seq += 1
                    self._json(
                        {
                            "client_id": f"client-{owner._seq}",
                            "redirect_uris": body.get("redirect_uris") or [],
                            "token_endpoint_auth_method": "none",
                        }
                    )
                    return
                form = parse_qs(raw)
                if parsed.path == "/token":
                    grant = form.get("grant_type", [""])[0]
                    owner._seq += 1
                    if grant == "refresh_token":
                        self._json(
                            {
                                "access_token": f"access-{owner._seq}",
                                "refresh_token": form.get("refresh_token", ["refresh"])[0],
                                "token_type": "Bearer",
                                "expires_in": 3600,
                            }
                        )
                        return
                    code = form.get("code", [""])[0]
                    expected = owner.codes.get(code)
                    verifier = form.get("code_verifier", [""])[0]
                    digest = hashlib.sha256(verifier.encode("ascii")).digest()
                    actual = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
                    if not expected or actual != expected:
                        self.send_error(400)
                        return
                    del owner.codes[code]
                    self._json(
                        {
                            "access_token": f"access-{owner._seq}",
                            "refresh_token": f"refresh-{owner._seq}",
                            "token_type": "Bearer",
                            "expires_in": 3600,
                        }
                    )
                    return
                if parsed.path == "/revoke":
                    owner.revoked.append(form.get("token", [""])[0])
                    self._json({"revoked": True})
                    return
                self.send_error(404)

            def _json(self, body: dict[str, object]) -> None:
                data = json.dumps(body).encode("utf-8")
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
