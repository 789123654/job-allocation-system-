"""Sentry SDK options and event scrubbing — what may leave the process for a third party.

Why this is more than `dsn=`: with the SDK's DEFAULTS (verified 2026-09-19 against sentry-sdk
2.68.1 by capturing a real event from a FastAPI app with `send_default_pii` unset, and against
Sentry's options docs), an error event carries
  - the request BODY (`request.data`) — `max_request_body_size` defaults to "medium"; for this
    product that is a firm's task titles/descriptions;
  - the LOCAL VARIABLES of every stack frame (`include_local_variables` defaults to True) — which
    include the ASGI `scope`/`request` objects, i.e. the raw `Authorization: Bearer <JWT>` header
    even though `request.headers.authorization` itself shows "[Filtered]", plus any variable
    holding client data;
  - database errors whose Postgres message echoes the offending value (core/redaction.py).
`send_default_pii` alone does not cover any of these. Logging_Cheat_Sheet.md "Data to exclude"
(access tokens, commercially-sensitive information), TCASVS 3.2.3, ASVS 16.2.5.

The cost, stated: an event has no local-variable snapshot and no request body, so a bug that needs
the failing input to reproduce has to be reproduced from the request id + route + tenant id in the
JSON logs (docs/OBSERVABILITY.md). The stack trace, source context, tags, release and environment
are unchanged.
"""

from typing import Any

from app.core.redaction import redact_db_values


def _redact_in(container: Any, key: str) -> None:
    if isinstance(container, dict):
        entry: dict[str, Any] = container  # pyright: ignore[reportUnknownVariableType]
        value = entry.get(key)
        if isinstance(value, str):
            entry[key] = redact_db_values(value)


def scrub_event(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    """`before_send`: redact database-echoed values from every free-text field of an event."""
    for exception in event.get("exception", {}).get("values", []):
        _redact_in(exception, "value")
    for key in ("message", "formatted"):
        _redact_in(event.get("logentry"), key)
    _redact_in(event, "message")
    for crumb in event.get("breadcrumbs", {}).get("values", []):
        _redact_in(crumb, "message")
    return event


def sentry_init_kwargs(*, dsn: str, release: str | None, environment: str | None) -> dict[str, Any]:
    return {
        "dsn": dsn,
        "release": release,
        "environment": environment,
        # 100% of requests traced: nowhere near the free tier's 5M spans/month at pilot scale
        # (Sentry pricing page, checked 2026-09-19; DEPLOYMENT.md §6). Revisit if usage says so.
        "traces_sample_rate": 1.0,
        # `send_default_pii` is deliberately NOT set (default off) — see the module docstring for
        # the two options that ALSO have to be off for that to mean anything.
        "include_local_variables": False,
        "max_request_body_size": "never",
        "before_send": scrub_event,
    }
