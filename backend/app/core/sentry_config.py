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

BATCH 2 (2026-09-22): a runtime probe (real sentry-sdk 2.68.1, real FastAPI app, a no-network
capture Transport — not read from Sentry's docs, which don't state exact field paths) found three
more channels the first version never touched: `event["request"]["query_string"]` (present on BOTH
error AND transaction events — `before_send` alone never saw a transaction event at all, a separate
`before_send_transaction` hook is required, confirmed live against Sentry's own filtering docs),
`breadcrumbs[].data` (an `http`-type breadcrumb's `url`/`query_string`, distinct from the already-
scrubbed `message`), and `logentry.params` (confirmed REACHABLE, not theoretical: this project's own
`logger.*()` calls are 100% `%`-style, e.g. `deps.py:62`, `employees.py:78` — the exact shape that
populates `params` as a raw list, separate from the already-scrubbed `message`/`formatted`).

`redact_db_values` only recognises Postgres error-message SHAPES — it does nothing for an arbitrary
query-string token, which has no recognisable structure to pattern-match (same problem batch 1's
`req_16` hit for frontend breadcrumb attribute values). So query strings/paths are FAIL-CLOSED:
stripped entirely, not selectively redacted, matching ASVS 14.2.1 ("sensitive data... never in URL/
query string" — this app should never rely on Sentry to guess which params are safe). `logentry.
params` keeps going through `redact_db_values` (defense in depth for the case a DB-echoed value ends
up there), consistent with how `message`/`formatted` are already treated.

A blind, attacker-mindset independent test pass (2026-09-22, given only this contract, not the
implementation) found three more real gaps, all reproduced against the code above before being
trusted: (1) `event["breadcrumbs"]` as a bare list, not `{"values": [...]}`, crashed this function
with `AttributeError` — a crash inside `before_send`/`before_send_transaction` is worse than a leak
(ASVS 16.5.3), now degrades to "scrub nothing this round" instead of raising; (2) a parameterized
route's `event["transaction"]` is already safely templated (e.g. `/reset/{token}`, confirmed
identical on error AND transaction events), but `request["url"]` independently carries the literal
matched path with no query string involved — the query-only strip missed it, now the whole path is
dropped too, same as the query string; (3) `event["extra"]` (arbitrary keys to arbitrary values, no
fixed shape or depth) had its per-value `redact_db_values` pass miss a secret nested in a dict-of-
list, a list-of-strings value, and a plain secret under an innocuous key name — now FAIL-CLOSED like
query strings, since a shallow shape-based redact can't safely cover an unbounded structure.
"""

from typing import Any
from urllib.parse import urlsplit, urlunsplit

from app.core.redaction import redact_db_values

_STRIPPED_QUERY = "[stripped: ASVS 14.2.1, never sent to Sentry]"


def _redact_in(container: Any, key: str) -> None:
    if isinstance(container, dict):
        entry: dict[str, Any] = container  # pyright: ignore[reportUnknownVariableType]
        value = entry.get(key)
        if isinstance(value, str):
            entry[key] = redact_db_values(value)


def _redact_each_in(container: Any, key: str) -> None:
    """Like `_redact_in`, for a list value (`logentry.params`)."""
    if isinstance(container, dict):
        entry: dict[str, Any] = container  # pyright: ignore[reportUnknownVariableType]
        values = entry.get(key)
        if isinstance(values, list):
            entry[key] = [
                redact_db_values(v) if isinstance(v, str) else v
                for v in values  # pyright: ignore[reportUnknownVariableType]
            ]


def _strip_url_path_and_query(url: str) -> str:
    """Keep only scheme+host. The PATH is dropped too, not just query/fragment (batch-2 blind-test
    finding, confirmed live 2026-09-22): a parameterized route's `event["transaction"]` already
    holds the safe route TEMPLATE (e.g. `/reset/{token}`, confirmed identical on both before_send
    and before_send_transaction events), but `request["url"]` independently carries the literal
    path Starlette actually matched (`/reset/RESETTOKENSECRET999`) -- no query string involved, so
    the earlier query-only strip missed it entirely. This app's current routes only ever put a UUID
    in a path segment (checked directly against every `@router.*` path in app/api/routes/), but the
    mechanism is general -- ASVS 14.2.1's principle ("never in URL") isn't scoped to just the query
    component, and the route template is already available for debugging, so nothing is lost.
    """
    parts = urlsplit(url)
    if not parts.path and not parts.query and not parts.fragment:
        return url
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def _strip_query_string(container: Any) -> None:
    """FAIL CLOSED on `event["request"]` or a breadcrumb's `data`: a query string/fragment/path is
    arbitrary client-supplied text with no recognisable shape to pattern-match (unlike a Postgres
    error message), so it is stripped entirely rather than selectively redacted — same reasoning as
    batch 1's `req_16` frontend fix.
    """
    if not isinstance(container, dict):
        return
    entry: dict[str, Any] = container  # pyright: ignore[reportUnknownVariableType]
    if "query_string" in entry:
        entry["query_string"] = _STRIPPED_QUERY
    if "fragment" in entry:
        entry["fragment"] = _STRIPPED_QUERY
    url = entry.get("url")
    if isinstance(url, str):
        entry["url"] = _strip_url_path_and_query(url)


def _breadcrumb_entries(event: dict[str, Any]) -> list[Any]:
    """`event["breadcrumbs"]["values"]`, tolerant of a malformed/unexpected shape. A blind-test
    finding (2026-09-22): `event.get("breadcrumbs", {}).get("values", [])` raised AttributeError
    when breadcrumbs was ever a bare list rather than `{"values": [...]}` -- a crash inside
    before_send/before_send_transaction is worse than a leak (ASVS 16.5.3, no fail-open on an
    internal error), so this degrades to "scrub nothing this round" instead of raising.
    """
    breadcrumbs = event.get("breadcrumbs")
    if isinstance(breadcrumbs, dict):
        bc: dict[str, Any] = breadcrumbs  # pyright: ignore[reportUnknownVariableType]
        values = bc.get("values")
        if isinstance(values, list):
            result: list[Any] = values  # pyright: ignore[reportUnknownVariableType]
            return result
    return []


def scrub_event(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    """`before_send` AND `before_send_transaction`: redact database-echoed values from every
    free-text field of an event, and strip query strings/paths and `extra` entirely. Shared between
    both hooks — every access below is `.get()`-guarded, so it is safe against either event shape (a
    transaction event has no `exception`/`logentry`, an error event usually has no `spans`).
    """
    for exception in event.get("exception", {}).get("values", []):
        _redact_in(exception, "value")
    for key in ("message", "formatted"):
        _redact_in(event.get("logentry"), key)
    _redact_each_in(event.get("logentry"), "params")
    _redact_in(event, "message")
    for raw_crumb in _breadcrumb_entries(event):
        if not isinstance(raw_crumb, dict):
            continue
        crumb: dict[str, Any] = raw_crumb  # pyright: ignore[reportUnknownVariableType]
        _redact_in(crumb, "message")
        _strip_query_string(crumb.get("data"))
    _strip_query_string(event.get("request"))
    # extra is FAIL CLOSED (batch-2 blind-test finding, 2026-09-22), not selectively redacted like
    # message/params above: it is "arbitrary keys to arbitrary values" with no fixed shape or depth
    # limit -- a shallow per-value redact_db_values pass missed a value nested in a dict-of-list, a
    # list-of-strings value, and a plain secret under an innocuous-sounding key. No code in app/
    # currently populates it (grepped, zero `set_extra`/`scope.set_extra` calls) -- this protects
    # whatever a future call site adds without anyone remembering to extend this function again.
    if isinstance(event.get("extra"), dict) and event["extra"]:
        event["extra"] = {"_stripped": _STRIPPED_QUERY}
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
        # before_send is NOT called for transaction/performance events (confirmed live against
        # Sentry's own filtering docs, 2026-09-22) -- a separate hook is required, or the same
        # request.query_string leak req_01 fixes for errors keeps happening on every transaction,
        # unscrubbed, at this app's 100% traces_sample_rate. scrub_event's own field access is
        # .get()-guarded against either event shape, so the same function covers both hooks.
        "before_send_transaction": scrub_event,
    }
