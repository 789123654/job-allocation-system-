"""Bound SQL parameter values must never reach an exception message, the JSON log line, or Sentry.

Found 2026-09-19 while verifying the structured logs: the 500 handler's `exc` field for a failed
statement contained `[SQL: SELECT ...] [parameters: {'firm_id_1': UUID(...), ...}]` — SQLAlchemy
appends the bound parameters to a DBAPIError's message by default. Here they were UUIDs, but the
same happens for ANY failing statement, so a failed INSERT/UPDATE would put a firm's task title or
description (commercially sensitive client data — Logging_Cheat_Sheet.md "Data to exclude",
TCASVS 3.2.3, ASVS 16.2.5) into Railway's logs and Sentry's exception value. `create_engine(...,
hide_parameters=True)` is the documented switch (SQLAlchemy 2.0 engines docs: parameters "will not
be displayed in INFO logging nor will they be formatted into the string representation of
StatementError objects"); the SQL text itself is kept, so errors stay debuggable.

The behavior tests need a real Postgres (a driver error is the thing under test) — same skip
pattern as tests/api/test_authz_regression.py.
"""

import logging
import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.db import engine
from app.core.logging_setup import JsonFormatter

_SENTINEL = "CLIENT-CONFIDENTIAL-TASK-DESCRIPTION-7f3a"

_NEEDS_PG = pytest.mark.skipif(
    not (os.environ.get("TEST_DATABASE_URL") and os.environ.get("TEST_MIGRATIONS_DATABASE_URL")),
    reason="needs a real Postgres — TEST_DATABASE_URL/TEST_MIGRATIONS_DATABASE_URL (CI does)",
)


def test_the_app_engine_is_configured_to_hide_statement_parameters() -> None:
    assert engine.hide_parameters is True


def _failing_statement_error() -> DBAPIError:
    with pytest.raises(DBAPIError) as caught, engine.connect() as conn:
        # `bad` cannot be a uuid, so the server rejects the statement. `note` is an innocent
        # bystander parameter: Postgres never mentions it, so it can only reach the message through
        # SQLAlchemy's own parameter dump — which is what this file is about.
        conn.execute(
            text("SELECT CAST(:bad AS uuid), :note AS note"),
            {"bad": "not-a-uuid", "note": _SENTINEL},
        )
    return caught.value


@_NEEDS_PG
def test_a_failed_statement_error_message_has_no_parameter_dump() -> None:
    message = str(_failing_statement_error())
    assert _SENTINEL not in message
    assert "[parameters:" not in message
    assert "SELECT CAST" in message  # the statement shape stays, so the error is still debuggable


@_NEEDS_PG
def test_the_json_log_line_for_a_failed_statement_omits_the_bound_values() -> None:
    error = _failing_statement_error()
    record = logging.LogRecord(
        name="app",
        level=logging.ERROR,
        pathname=__file__,
        lineno=0,
        msg="Unhandled exception on %s",
        args=("/tasks",),
        exc_info=(type(error), error, error.__traceback__),
    )
    line = JsonFormatter().format(record)
    assert _SENTINEL not in line
    assert '"exc"' in line  # the traceback is still there
