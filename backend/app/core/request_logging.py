"""Access log + request id, as a pure ASGI middleware.

Not `@app.middleware("http")`: Starlette documents that BaseHTTPMiddleware breaks ContextVar
propagation, and this needs the request context visible to everything downstream. Added LAST in
main.py so it is the outermost user middleware and sees every response, including CORS's and the
security-headers middleware's.

Logs the route TEMPLATE, never the raw path, query string, headers or body (ASVS 14.2.1,
TCASVS 3.2.3, Logging_Cheat_Sheet.md "Data to exclude"): an unmatched request's path is
attacker-controlled text and a query string can carry anything.
"""

import contextlib
import logging
import time

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core import request_context, runtime_stats

_logger = logging.getLogger("app.access")
_MAX_METHOD_LEN = 16


def _log_access(scope: Scope, status: int, started: float) -> None:
    # Logging must never change what the client gets (ASVS 16.5.2): a failure here is swallowed.
    with contextlib.suppress(Exception):
        # FastAPI's APIRoute.matches() puts itself in scope["route"]; plain Starlette routes
        # (/docs, /openapi.json) don't, so they log as "<unmatched>" - a known, harmless quirk.
        route = scope.get("route")
        borrowed, total = runtime_stats.threadpool_stats()
        checked_out, capacity = runtime_stats.pool_stats()
        _logger.info(
            "request",
            extra={
                "method": str(scope.get("method", ""))[:_MAX_METHOD_LEN],
                "route": getattr(route, "path", None) or "<unmatched>",
                "status": status,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "pool_checked_out": checked_out,
                "pool_capacity": capacity,
                "threadpool_borrowed": borrowed,
                "threadpool_total": total,
            },
        )


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # A fresh id per request, ignoring any client-supplied X-Request-ID: an id the client picks
        # is a way to forge or collide log correlation.
        ctx = request_context.start_request()
        started = time.perf_counter()
        status = 500  # what an unhandled exception ends up as (main.py's handler answers later)

        async def send_with_request_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = ctx["request_id"]
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            _log_access(scope, status, started)
