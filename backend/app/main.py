from collections.abc import Awaitable, Callable
from http import HTTPStatus

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.main import api_router
from app.core.config import settings

app = FastAPI(title="CA Firm Practice Management API")

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
        media_type="application/problem+json",
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


app.include_router(api_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
