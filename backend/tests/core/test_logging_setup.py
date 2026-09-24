"""JSON log formatting and handler setup (app/core/logging_setup.py).

ASVS 16.4.1 (encode against log injection), 16.2.2 (UTC), 16.2.4 (one parseable format) and
Logging_Cheat_Sheet.md "Data to exclude"/"Attacks on Logs".
"""

import contextvars
import json
import logging
import sys
from collections.abc import Callable
from datetime import datetime as dt
from datetime import timedelta
from typing import Any

import pytest

from app.core import request_context
from app.core.logging_setup import (
    _HANDLER_MARK,  # pyright: ignore[reportPrivateUsage]
    ALLOWED_EXTRA_FIELDS,
    JsonFormatter,
    configure_logging,
)


def _format(message: str, **extra: object) -> str:
    record = logging.LogRecord("app.test", logging.INFO, __file__, 1, message, None, None)
    for key, value in extra.items():
        setattr(record, key, value)
    return JsonFormatter().format(record)


def _isolated(fn: Callable[[], None]) -> None:
    contextvars.Context().run(fn)


def test_every_record_has_the_fixed_keys_and_a_utc_timestamp() -> None:
    def body() -> None:
        payload = json.loads(_format("hello"))
        assert {"ts", "level", "logger", "message", "request_id", "tenant_id"} <= payload.keys()
        assert {"actor_id", "actor_role"} <= payload.keys()
        assert payload["level"] == "INFO"
        assert payload["logger"] == "app.test"
        assert payload["message"] == "hello"
        assert payload["request_id"] is None  # outside a request
        assert dt.fromisoformat(payload["ts"]).utcoffset() == timedelta(0)

    _isolated(body)


def test_identity_from_the_current_request_is_included() -> None:
    def body() -> None:
        ctx = request_context.start_request()
        request_context.bind_identity(tenant_id="11111111-1111-4111-8111-111111111111")
        payload = json.loads(_format("hi"))
        assert payload["request_id"] == ctx["request_id"]
        assert payload["tenant_id"] == "11111111-1111-4111-8111-111111111111"

    _isolated(body)


def test_control_characters_cannot_forge_or_split_a_line() -> None:
    """Log injection (CWE-117): a newline in attacker text must not become a second log line."""
    hostile = 'ok\n{"level":"CRITICAL","message":"forged"}\r\u2028\u2029\x00'
    line = _format(hostile, route=hostile)
    assert "\n" not in line
    assert "\r" not in line
    payload = json.loads(line)
    assert payload["message"] == hostile  # preserved, but only as data inside ONE string value
    assert payload["level"] == "INFO"


def test_only_allowlisted_extra_fields_are_emitted() -> None:
    payload = json.loads(_format("x", route="/tasks/{task_id}", email="a@b.example", body="secret"))
    assert payload["route"] == "/tasks/{task_id}"
    assert "email" not in payload
    assert "body" not in payload


def test_allowlist_is_exactly_the_reviewed_set() -> None:
    """Structural guard (code-review root cause E): adding a field means editing this test too."""
    assert set(ALLOWED_EXTRA_FIELDS) == {
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
    }
    reserved = set(logging.LogRecord("n", 0, "p", 1, "m", None, None).__dict__) | {"message"}
    assert not reserved & set(ALLOWED_EXTRA_FIELDS)  # extra={...} with these would raise KeyError


def test_huge_messages_and_fields_are_truncated() -> None:
    line = _format("m" * 200_000, route="r" * 200_000)
    assert len(line) < 20_000
    payload = json.loads(line)
    assert payload["message"].endswith("...[truncated]")
    assert payload["route"].endswith("...[truncated]")


def test_non_finite_floats_become_null_so_the_line_stays_valid_json() -> None:
    payload = json.loads(_format("x", duration_ms=float("nan"), utilization=float("inf")))
    assert payload["duration_ms"] is None
    assert payload["utilization"] is None


def test_exception_info_goes_in_exc() -> None:
    try:
        raise ValueError("boom-detail")
    except ValueError:
        record = logging.LogRecord(
            "app.test", logging.ERROR, __file__, 1, "failed", None, sys.exc_info()
        )
    payload = json.loads(JsonFormatter().format(record))
    assert "ValueError" in payload["exc"]
    assert "boom-detail" in payload["exc"]


# BATCH 3 (SECURITY_AUDIT_CHECKLIST.md req_41+): FastAPI's ResponseValidationError embeds the raw
# offending value in its own __str__ via a Pydantic error dict. Shape confirmed live (session
# scratchpad probe_batch3_response_validation.py) against the real app: `str(exc)` appears verbatim
# as the traceback's last line(s), exactly reproduced here without importing fastapi's routing
# (keeps this a unit test of JsonFormatter's redaction, not an integration test of FastAPI routing).
def test_response_validation_error_message_is_stripped_from_exc() -> None:
    from fastapi.exceptions import ResponseValidationError

    secret = "SSN-REVEAL-ME-123456789"
    try:
        raise ResponseValidationError(
            errors=[{"type": "int_parsing", "loc": ("response", "ssn"), "input": secret}]
        )
    except ResponseValidationError:
        record = logging.LogRecord(
            "app.test", logging.ERROR, __file__, 1, "failed", None, sys.exc_info()
        )
    payload = json.loads(JsonFormatter().format(record))
    assert secret not in payload["exc"]
    assert "ResponseValidationError" in payload["exc"]  # exception class stays visible


def test_a_chained_response_validation_error_is_also_stripped() -> None:
    """The real path (main.py's unhandled_exception_handler) re-raises via a chain (`raise app_exc
    from app_exc.__cause__ or app_exc.__context__`), not a bare top-level exception -- this proves
    the __cause__/__context__ walk actually finds it, not just a top-level exc_info[1]."""
    from fastapi.exceptions import ResponseValidationError

    secret = "CHAINED-SECRET-VALUE"
    try:
        try:
            raise ResponseValidationError(errors=[{"type": "string_type", "input": secret}])
        except ResponseValidationError as inner:
            raise RuntimeError("outer safe message") from inner
    except RuntimeError:
        record = logging.LogRecord(
            "app.test", logging.ERROR, __file__, 1, "failed", None, sys.exc_info()
        )
    payload = json.loads(JsonFormatter().format(record))
    assert secret not in payload["exc"]
    assert "outer safe message" in payload["exc"]  # the safe outer message is untouched


def test_a_plain_exception_with_no_validation_error_in_its_chain_is_unaffected() -> None:
    """Non-vacuity: this must not turn into a blanket strip of every traceback."""
    try:
        raise ValueError("ordinary error, nothing to strip")
    except ValueError:
        record = logging.LogRecord(
            "app.test", logging.ERROR, __file__, 1, "failed", None, sys.exc_info()
        )
    payload = json.loads(JsonFormatter().format(record))
    assert "ordinary error, nothing to strip" in payload["exc"]


# Blind-test finding (2026-09-22): the exc_info-based fix above only protects a call site using
# `logger.exception(...)`/`exc_info=True`. A call site that logs str(exc) as the plain MESSAGE
# instead -- no exc_info attached -- has no live exception object for that fix to match against.
# This app's one real call site (main.py's catch-all handler) always uses logger.exception and is
# unaffected, but nothing stops a future `logger.error(f"...: {exc}")` one-liner from reopening
# this, so it's closed by recognising Pydantic's fixed error-dict repr signature in the text itself.
def test_a_validation_error_logged_as_the_plain_message_with_no_exc_info_is_also_stripped() -> None:
    from fastapi.exceptions import ResponseValidationError

    secret = "SSN-REVEAL-ME-123456789"
    exc = ResponseValidationError(
        errors=[{"type": "string_type", "loc": ("response", "x"), "msg": "bad", "input": secret}]
    )
    record = logging.LogRecord("app.test", logging.ERROR, __file__, 1, str(exc), None, None)
    payload = json.loads(JsonFormatter().format(record))
    assert secret not in payload["message"]
    assert record.exc_info is None  # confirms this really is the no-exc_info path, not req_41's


def test_an_ordinary_message_that_happens_to_mention_input_is_not_stripped() -> None:
    """Non-vacuity: the signature match needs all three markers together, not just one common word."""
    payload = json.loads(_format("please check the input field on the form"))
    assert payload["message"] == "please check the input field on the form"


def test_configure_logging_is_idempotent_and_writes_json_to_the_live_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging()
    configure_logging()
    root = logging.getLogger()
    assert sum(1 for h in root.handlers if getattr(h, _HANDLER_MARK, False)) == 1

    capsys.readouterr()
    logging.getLogger("app.test").warning("once")
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert len(lines) == 1  # not doubled by the second configure_logging()
    parsed: dict[str, Any] = json.loads(lines[0])
    assert parsed["message"] == "once"


def test_uvicorns_own_access_log_is_disabled() -> None:
    """It logs the raw path AND query string (ASVS 14.2.1) and would duplicate app.access."""
    configure_logging()
    assert logging.getLogger("uvicorn.access").disabled is True


def test_a_broken_stdout_never_raises_into_the_caller(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenStream:
        def write(self, _text: str) -> int:
            raise OSError("stdout closed")

        def flush(self) -> None:
            raise OSError("stdout closed")

    configure_logging()
    monkeypatch.setattr(sys, "stdout", BrokenStream())
    logging.getLogger("app.test").warning("must not raise")  # ASVS 16.5.2
