"""Optional bearer gate for internet-facing self-hosted deployments."""

from __future__ import annotations

import os
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


def _open_paths() -> frozenset[str]:
    if os.environ.get("VINCI_DESKTOP") == "1":
        return frozenset({"/healthz"})
    return frozenset({"/healthz", "/handshake", "/providers/oauth/callback"})


class BridgeAuthMiddleware(BaseHTTPMiddleware):
    """Require Authorization: Bearer <VINCI_BRIDGE_TOKEN> except health checks."""

    async def dispatch(self, request: Request, call_next) -> Response:
        token = os.environ.get("VINCI_BRIDGE_TOKEN", "").strip()
        if not token:
            return await call_next(request)
        if request.url.path in _open_paths():
            return await call_next(request)
        auth = request.headers.get("authorization", "")
        expected = f"Bearer {token}"
        if secrets.compare_digest(auth, expected):
            return await call_next(request)
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
