import logging
from collections.abc import Awaitable, Callable
from http import HTTPStatus

import sentry_sdk
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.main import api_router
from app.core.config import settings

logger = logging.getLogger("app")

if settings.SENTRY_DSN:
    # Must run before FastAPI(...) below — Sentry's FastAPI integration auto-instruments on
    # sentry_sdk.init(), no explicit integrations=[...] needed for this (verified against Sentry's
    # own current FastAPI integration docs, not assumed from an older API shape).
    #
    # traces_sample_rate=1.0 (100% of requests traced, not a partial sample): at this project's
    # actual pilot scale this is nowhere near Sentry's free-tier 5M-spans/month cap (real margin,
    # not guessed — see DEPLOYMENT.md §6); revisit downward only if real usage stats ever say
    # otherwise, not pre-emptively.
    #
    # send_default_pii deliberately NOT set (defaults to False) — Sentry's own quickstart examples
    # default this to True, which would forward request bodies/headers/user IP to a third-party
    # service by default. This project already treats user/tenant context as sensitive (audit_log,
    # access_denials) and that same care applies to a new external destination — a call this
    # project makes deliberately, not one inherited from a docs example (skill-verification-
    # discipline.md failure mode 7: a new destination for data needs its own check, not the
    # mechanism's default).
    #
    # No profiling flags (profile_session_sample_rate/profile_lifecycle) — Sentry's continuous
    # profiling requires a paid add-on even on the free Developer plan (verified live against
    # Sentry's own pricing page, 2026-09-08); tracing alone already answers "how long did this
    # request take," which is all this was built for.
    sentry_sdk.init(dsn=settings.SENTRY_DSN, traces_sample_rate=1.0)

class _UTF8JSONResponse(JSONResponse):
    """Starlette's JSONResponse never appends `charset` to Content-Type — it only does that for
    `text/*` media types (checked directly in starlette/responses.py, not assumed). ASVS 5 §4.1.1
    requires an explicit charset on every response with a body; Error_Handling_Cheat_Sheet.md's own
    examples set `application/json; charset=UTF-8` explicitly for exactly this reason. Applied as
    the app-wide default so every route (Phase 1's /health today, every later resource's responses)
    gets this for free, not just the problem+json error responses below.
    """

    media_type = "application/json; charset=utf-8"


app = FastAPI(title="CA Firm Practice Management API", default_response_class=_UTF8JSONResponse)

# Explicit allowlist only — never "*", never "*" + credentials (API_SPEC.md §1).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
)

_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "frame-ancestors 'none'",
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
}


@app.middleware("http")
async def add_security_headers(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Required on every response a browser client sees (REST_Security_Cheat_Sheet.md, Security
    Headers) — the Tauri webview is exactly that, even though it's not a general browser. The
    HTML-only headers in that table (Permissions-Policy, the broader CSP, Referrer-Policy) are
    skipped: this API never returns HTML, only JSON/problem+json, which the sheet states plainly
    they add no protection for.
    """
    response = await call_next(request)
    response.headers.update(_SECURITY_HEADERS)
    return response


def _problem(status_code: int, detail: str, instance: str) -> JSONResponse:
    """RFC 9457 problem+json, per API_SPEC.md §1 Rule 176/177 — no stack traces, ever."""
    slug = HTTPStatus(status_code).phrase.lower().replace(" ", "-")
    return JSONResponse(
        status_code=status_code,
        media_type="application/problem+json; charset=utf-8",
        content={
            "type": f"/problems/{slug}",
            "title": HTTPStatus(status_code).phrase,
            "status": status_code,
            "detail": detail,
            "instance": instance,
        },
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return _problem(exc.status_code, str(exc.detail), str(request.url.path))


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return _problem(422, "Request validation failed", str(request.url.path))


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Error_Handling_Cheat_Sheet.md: a bug must never fall through to a raw framework 500 —
    genuine unhandled exceptions still get the app's own problem+json shape, with the real
    exception logged server-side (this handler's job) and never echoed to the client (`_problem`'s
    job, already true of every other handler here).
    """
    # Starlette invokes this handler from inside its own `except` block, so sys.exc_info() is live
    # and .exception() captures the real traceback. Ruff's LOG004 is purely syntactic and can't see
    # that the @app.exception_handler decorator establishes that context.
    logger.exception("Unhandled exception on %s", request.url.path)  # noqa: LOG004
    return _problem(500, "An unexpected error occurred", str(request.url.path))


app.include_router(api_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
