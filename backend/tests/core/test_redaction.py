"""core/redaction.py: database-echoed values never survive into log lines or Sentry text.

Message shapes below were captured from a real Postgres 17 through psycopg + SQLAlchemy (the live
tests at the bottom regenerate them, so a change in server wording fails here, not silently).
"""

import logging
import os
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.db import engine
from app.core.logging_setup import JsonFormatter
from app.core.redaction import redact_db_values

# Deliberately nasty: a double quote and a newline inside the value, like a real multi-line note.
_SECRET = 'Acme "Holdings" Pvt\nLtd SECRET-7f3a'

_NEEDS_PG = pytest.mark.skipif(
    not (os.environ.get("TEST_DATABASE_URL") and os.environ.get("TEST_MIGRATIONS_DATABASE_URL")),
    reason="needs a real Postgres — TEST_DATABASE_URL/TEST_MIGRATIONS_DATABASE_URL (CI does)",
)

_TAIL = (
    "[SQL: SELECT CAST(%(v)s AS uuid)]\n"
    "(Background on this error at: https://sqlalche.me/e/20/9h9h)"
)


def test_a_quoted_value_echoed_in_the_first_line_is_removed() -> None:
    raw = (
        "(psycopg.errors.InvalidTextRepresentation) "
        'invalid input syntax for type uuid: "SECRET-7f3a"\n'
        "CONTEXT:  unnamed portal parameter $1 = '...'\n" + _TAIL
    )
    out = redact_db_values(raw)
    assert "SECRET-7f3a" not in out
    assert "invalid input syntax for type uuid" in out
    assert "[SQL: SELECT CAST(%(v)s AS uuid)]" in out


def test_a_unique_violation_detail_is_removed_but_the_constraint_name_stays() -> None:
    raw = (
        "(psycopg.errors.UniqueViolation) "
        'duplicate key value violates unique constraint "t_x_name_key"\n'
        "DETAIL:  Key (name)=(Acme Holdings SECRET-7f3a) already exists.\n"
        "[SQL: INSERT INTO t_x(name) VALUES (%(v)s)]"
    )
    out = redact_db_values(raw)
    assert "SECRET-7f3a" not in out
    assert 'unique constraint "t_x_name_key"' in out
    assert "[SQL: INSERT INTO t_x(name) VALUES (%(v)s)]" in out


def test_a_failing_row_that_spans_lines_is_removed_entirely() -> None:
    raw = (
        "(psycopg.errors.NotNullViolation) "
        'null value in column "name" violates not-null constraint\n'
        "DETAIL:  Failing row contains (5, null, first line SECRET-7f3a\n"
        "second line CONFIDENTIAL).\n"
        "[SQL: INSERT INTO t_x(name, note) VALUES (NULL, %(v)s)]"
    )
    out = redact_db_values(raw)
    assert "SECRET-7f3a" not in out
    assert "CONFIDENTIAL" not in out
    assert "not-null constraint" in out
    assert "[SQL: INSERT" in out


def test_a_multi_line_context_block_is_removed_entirely() -> None:
    raw = (
        "(psycopg.errors.InvalidTextRepresentation) invalid input syntax for type json\n"
        'DETAIL:  Token "SECRET-7f3a" is invalid.\n'
        "CONTEXT:  JSON data, line 1: SECRET-7f3a...\n"
        "unnamed portal parameter $1 = '...'\n"
        "[SQL: SELECT CAST(%(v)s AS jsonb)]"
    )
    out = redact_db_values(raw)
    assert "SECRET-7f3a" not in out
    assert "unnamed portal parameter" not in out
    assert "invalid input syntax for type json" in out
    assert "[SQL: SELECT CAST" in out


def test_redaction_stops_at_the_traceback_structure_that_follows() -> None:
    raw = (
        'psycopg.errors.UniqueViolation: duplicate key value violates unique constraint "k"\n'
        "DETAIL:  Key (name)=(SECRET-7f3a) already exists.\n"
        "\n"
        "The above exception was the direct cause of the following exception:\n"
        "\n"
        "Traceback (most recent call last):\n"
        '  File "app/crud.py", line 1, in create\n'
    )
    out = redact_db_values(raw)
    assert "SECRET-7f3a" not in out
    assert "The above exception was the direct cause" in out
    assert 'File "app/crud.py", line 1, in create' in out


@pytest.mark.parametrize(
    "ordinary",
    [
        'KeyError: "task_id"',
        'ValueError: invalid literal for int() with base 10: "abc"',
        "RuntimeError: boom\nDETAIL and CONTEXT are just words here",
        "",
    ],
)
def test_text_that_is_not_a_database_error_is_left_alone(ordinary: str) -> None:
    assert redact_db_values(ordinary) == ordinary


def test_redaction_is_idempotent() -> None:
    raw = (
        "(psycopg.errors.UniqueViolation) duplicate key\n"
        "DETAIL:  Key (name)=(SECRET-7f3a) already exists.\n"
        "[SQL: INSERT INTO t(name) VALUES (%(v)s)]"
    )
    once = redact_db_values(raw)
    assert redact_db_values(once) == once


def test_the_json_log_line_redacts_a_database_error_in_the_message_field() -> None:
    record = logging.LogRecord(
        "app.auth",
        logging.ERROR,
        __file__,
        0,
        "db said: %s",
        ("(psycopg.errors.UniqueViolation) dup\nDETAIL:  Key (name)=(SECRET-7f3a) exists.",),
        None,
    )
    assert "SECRET-7f3a" not in JsonFormatter().format(record)


# ---------------------------------------------------------------- live, against a real Postgres


def _error_from(sql: str, params: dict[str, Any]) -> DBAPIError:
    with pytest.raises(DBAPIError) as caught, engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TEMP TABLE IF NOT EXISTS t_redact "
                "(id serial PRIMARY KEY, name text NOT NULL UNIQUE, note text)"
            )
        )
        conn.execute(text("INSERT INTO t_redact(name) VALUES ('taken'), (:s)"), {"s": _SECRET})
        conn.execute(text(sql), params)
    return caught.value


_LIVE_CASES: dict[str, tuple[str, dict[str, Any]]] = {
    "cast": ("SELECT CAST(:v AS uuid)", {"v": _SECRET}),
    "array": ("SELECT CAST(:v AS int[])", {"v": _SECRET}),
    "json": ("SELECT CAST(:v AS jsonb)", {"v": _SECRET}),
    "notnull": ("INSERT INTO t_redact(name, note) VALUES (NULL, :v)", {"v": _SECRET}),
    "unique": ("INSERT INTO t_redact(name) VALUES (:v)", {"v": _SECRET}),
}


@_NEEDS_PG
@pytest.mark.parametrize("case", sorted(_LIVE_CASES))
def test_live_database_errors_never_carry_the_value_into_a_log_line(case: str) -> None:
    sql, params = _LIVE_CASES[case]
    error = _error_from(sql, params)
    record = logging.LogRecord(
        "app",
        logging.ERROR,
        __file__,
        0,
        "Unhandled exception on %s",
        ("/tasks",),
        (type(error), error, error.__traceback__),
    )
    line = JsonFormatter().format(record)
    for fragment in ("SECRET-7f3a", "Acme", "Holdings"):
        assert fragment not in line, f"{case}: {fragment!r} reached the log line"
    assert '"exc"' in line
    assert "psycopg.errors" in line  # the error class survives: still debuggable


@_NEEDS_PG
def test_the_live_unique_violation_really_has_the_detail_this_module_redacts() -> None:
    # Guard against the tests above passing vacuously if Postgres changes its wording.
    error = _error_from("INSERT INTO t_redact(name) VALUES (:v)", {"v": "taken"})
    assert "Key (name)=(taken) already exists" in str(error)
    assert "already exists" not in redact_db_values(str(error))
