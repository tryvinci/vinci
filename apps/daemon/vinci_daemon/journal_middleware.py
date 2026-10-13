from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from vinci_storage.durable_journal import DurableJournal
from vinci_storage.durable_paths import classify_mutation


class JournalHealthMiddleware(BaseHTTPMiddleware):
    OPEN_PATHS = frozenset({"/healthz", "/handshake", "/__vinci/journal"})

    async def dispatch(self, request: Request, call_next) -> Response:
        journal: DurableJournal | None = getattr(request.app.state, "journal", None)
        if journal is not None and not journal.healthy():
            path = request.url.path
            if path not in self.OPEN_PATHS and not path.startswith("/__vinci/journal"):
                kind = classify_mutation(request.method, path)
                if kind is not None:
                    return JSONResponse(
                        {
                            "detail": "journal_unhealthy",
                            "error": journal.last_error(),
                        },
                        status_code=503,
                    )
        return await call_next(request)
