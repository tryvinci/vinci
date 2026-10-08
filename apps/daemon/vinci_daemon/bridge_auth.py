"""Optional bearer gate for internet-facing self-hosted deployments."""

from __future__ import annotations

import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


class BridgeAuthMiddleware(BaseHTTPMiddleware):
    """Require Authorization: Bearer <VINCI_BRIDGE_TOKEN> except health checks."""

    OPEN_PATHS = frozenset({"/healthz", "/handshake"})

    async def dispatch(self, request: Request, call_next) -> Response:
        token = os.environ.get("VINCI_BRIDGE_TOKEN", "").strip()
        if not token:
            return await call_next(request)
        if request.url.path in self.OPEN_PATHS:
            return await call_next(request)
        auth = request.headers.get("authorization", "")
        if auth == f"Bearer {token}":
            return await call_next(request)
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
