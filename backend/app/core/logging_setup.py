"""One JSON object per log line on stdout.

DEPLOYMENT.md §6: Railway captures stdout, and ASVS 16.2.4/16.4.1/16.2.2 want a common parseable
format, UTC timestamps and injection-safe encoding. `json.dumps` escapes every control character,
so attacker-controlled text (a header, a path, an exception message) can never forge or split a
log line (REST_Security_Cheat_Sheet.md, Logging_Cheat_Sheet.md "Attacks on Logs").
"""

import contextlib
import json
import logging
import math
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import TextIO

from fastapi.exceptions import ValidationException

from app.core import request_context
from app.core.redaction import redact_db_values

_MAX_MESSAGE = 8_192
_MAX_EXC = 16_384
_MAX_FIELD = 256

# BATCH 3 (2026-09-22): FastAPI's ResponseValidationError/RequestValidationError/
# WebSocketRequestValidationError (all ValidationException) embed the raw offending value(s) in
# their own __str__ via Pydantic error dicts ({'type': ..., 'loc': ..., 'msg': ..., 'input': <the
# actual value>}) -- confirmed live (session probe): a route returning a value that fails its
# response_model produces a traceback whose LAST line is `str(exc)` verbatim, and redact_db_values
# (Postgres-shape-only) does not recognise this shape at all, so it passed through unredacted.
# This does an EXACT string replacement of str(exc) for each such exception in the real chain object
# we already have (record.exc_info[1]) -- not a text pattern over the formatted traceback, which is
# exactly the "KNOWN LIMIT" redaction.py's own docstring already names as the real fix ("render
# exceptions from the exception object instead of from text"). Runs BEFORE redact_db_values, which
# still runs afterward for defense in depth on anything else in the same chain.
_STRIPPED_VALIDATION_TEXT = "[stripped: Pydantic validation-error input values, ASVS 16.2.5]"


def _validation_errors_in_chain(exc: BaseException | None) -> Iterator[ValidationException]:
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, ValidationException):
            yield exc
        exc = exc.__cause__ or exc.__context__


def _redact_validation_errors(formatted: str, exc: BaseException | None) -> str:
    for validation_exc in _validation_errors_in_chain(exc):
        raw = str(validation_exc)
        if raw:
            formatted = formatted.replace(raw, _STRIPPED_VALIDATION_TEXT)
    return formatted


# A blind-test pass (2026-09-22) found the fix above only protects the `exc` field (built from
# `record.exc_info`): a call site that logs a ValidationException's str() as the plain MESSAGE
# instead -- `logger.error(f"...: {exc}")`, no `exc_info` -- has no live exception object attached
# to the record for `_redact_validation_errors` to match against, only text. Reproduced live: this
# app's one current real call site (main.py's catch-all handler) always uses `logger.exception(...)`
# and is unaffected, but nothing stops a future one-liner from reopening this. Pydantic's error-dict
# repr is a FIXED, library-controlled literal format (the key names, not the values, are what's
# attacker-proof) -- recognising its signature is the same kind of safe, non-parsing match
# `_PG_TEMPLATES` already relies on for Postgres's own fixed message templates, not a new attempt to
# parse arbitrary text. Whole-message fail-closed on match, same reasoning as `extra`/query_string:
# there is no way to selectively redact just the `input` values from repr'd text without parsing it.
_VALIDATION_ERROR_MESSAGE_SIGNATURE = ("'type': ", "'loc': ", "'input': ")


def _redact_validation_error_message(message: str) -> str:
    if all(marker in message for marker in _VALIDATION_ERROR_MESSAGE_SIGNATURE):
        return _STRIPPED_VALIDATION_TEXT
    return message


# Structural allowlist (code-review root cause E: a rule that only exists as a comment gets
# skipped). A caller's `extra={...}` key that isn't listed here is silently dropped, so a future
# `logger.info(..., extra={"email": ...})` cannot put a new field into the logs without a
# deliberate edit, and a test, right here. Values are clipped/encoded in `_field`.
ALLOWED_EXTRA_FIELDS = (
    "event",
    "method",
    "route",
    "status",
    "duration_ms",
    "pool_checked_out",
    "pool_capacity",
    "threadpool_borrowed",
    "threadpool_total",
    "checked_out",
    "capacity",
    "utilization",
)

_HANDLER_MARK = "_app_json_stdout_handler"


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "...[truncated]"


def _field(value: object) -> object:
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None  # NaN/inf aren't valid JSON
    return _clip(str(value), _MAX_FIELD)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ctx = request_context.current()
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": _clip(
                redact_db_values(_redact_validation_error_message(record.getMessage())),
                _MAX_MESSAGE,
            ),
            "request_id": ctx["request_id"] if ctx else None,
            "tenant_id": ctx["tenant_id"] if ctx else None,
            "actor_id": ctx["actor_id"] if ctx else None,
            "actor_role": ctx["actor_role"] if ctx else None,
        }
        for key in ALLOWED_EXTRA_FIELDS:
            if key in record.__dict__:
                payload[key] = _field(record.__dict__[key])
        if record.exc_info:
            formatted = _redact_validation_errors(
                self.formatException(record.exc_info), record.exc_info[1]
            )
            payload["exc"] = _clip(redact_db_values(formatted), _MAX_EXC)
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), default=str)


class _LiveStdoutHandler(logging.StreamHandler[TextIO]):
    """Looks `sys.stdout` up at emit time — the stdlib's own `lastResort` handler does the same for
    stderr — so a swapped stdout (pytest's capsys, a wrapper) is honoured, not a stale reference.
    """

    def __init__(self) -> None:
        logging.Handler.__init__(self)

    @property
    def stream(self) -> TextIO:  # pyright: ignore[reportIncompatibleVariableOverride]
        return sys.stdout

    def handleError(self, record: logging.LogRecord) -> None:
        """The stdlib version prints the raw `Message:` and `Arguments:` of a malformed log call to
        stderr, which would put the very values the redactor exists to remove into a log stream the
        redactor never sees. Say only that a record failed, and which logger and error class."""
        error = sys.exc_info()[0]
        note = {
            "level": "ERROR",
            "logger": "app.logging",
            "message": "a log record could not be formatted",
            "failed_logger": record.name,
            "error": error.__name__ if error else None,
        }
        with contextlib.suppress(Exception):  # a logging failure must never raise into the caller
            sys.stderr.write(json.dumps(note, ensure_ascii=True, separators=(",", ":")) + "\n")


def configure_logging() -> None:
    """Idempotent — importing app.main twice (reloads, tests) must not double every line."""
    root = logging.getLogger()
    if not any(getattr(handler, _HANDLER_MARK, False) for handler in root.handlers):
        handler = _LiveStdoutHandler()
        handler.setFormatter(JsonFormatter())
        setattr(handler, _HANDLER_MARK, True)
        root.addHandler(handler)
    logging.getLogger("app").setLevel(logging.INFO)
    # uvicorn's own access line carries the raw path AND query string (ASVS 14.2.1: nothing
    # sensitive belongs in a URL log) and would duplicate the app.access record, which logs the
    # route template instead.
    logging.getLogger("uvicorn.access").disabled = True
    # uvicorn applies its OWN logging config when the server starts, after this module was imported,
    # which (a) re-enables the access logger above and (b) gives `uvicorn` a private stderr handler
    # with propagate=False. Starlette re-raises an unhandled exception after the app's 500 handler
    # ran, and uvicorn logs it on `uvicorn.error`: a second, UNREDACTED traceback. So the app calls
    # this again from its lifespan (main.py), which runs after uvicorn's config, and drops that
    # handler so those records reach the root handler and its redaction.
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
