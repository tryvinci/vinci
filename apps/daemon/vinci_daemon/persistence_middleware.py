from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from vinci_storage.home_persistence import HomePersistence


class PersistenceHealthMiddleware(BaseHTTPMiddleware):
    OPEN_PATHS = frozenset({"/healthz", "/handshake"})

    async def dispatch(self, request: Request, call_next) -> Response:
        persistence: HomePersistence | None = getattr(request.app.state, "persistence", None)
        if persistence is not None and not persistence.healthy:
            if request.url.path not in self.OPEN_PATHS:
                return JSONResponse(
                    {"detail": "persistence_unhealthy", "error": persistence.last_error},
                    status_code=503,
                )
        return await call_next(request)
