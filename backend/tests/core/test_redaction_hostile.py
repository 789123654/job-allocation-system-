"""Hostile-input tests for the exception-text redaction layer (batch 1 of the 2026-09-19 review
fixes).

Written BEFORE the fix, from an attacker's seat. The attacker controls a client-confidential VALUE
(a task description, a firm name) and wants it to survive into a log line or a Sentry event, or
wants to make the scrubber slow or blind. Attack inputs come from three places, none of them the
regexes in redaction.py:
  1. the STRUCTURE of the text Postgres / psycopg / SQLAlchemy / traceback produce, which a value
     can imitate;
  2. WSTG-ERRH-01's own techniques (oversized strings, CRLF, mismatched-type data);
  3. Unicode line separators and log-format lookalikes.
The error text is REAL: it is provoked on a live Postgres, not typed by hand (failure mode 9).

Each value is `MRK<hex>A` + payload + `MRK<hex>B`, so a partial leak (redaction that stops midway
through the value) shows up as the trailing marker surviving.

Properties (numbers refer to docs/SECURITY_AUDIT_CHECKLIST.md "Current Audit" rows):
  req_02  the marker never leaves, in any container (text, traceback, group, JSON log line, Sentry
          event)
  req_03  ...including chained causes and ExceptionGroup members
  req_04  the JSON log line stays one valid JSON line
  req_01  no super-linear time (scaling test) and bounded work on huge input
  req_07  a failing redactor fails CLOSED
  req_13  no new module formats exception text on its own
  P3      the error stays debuggable: class name, message template and traceback frames survive
  P4      text that is not a database error is untouched; redaction is idempotent and never raises
  req_17  KNOWN LIMIT: a value containing a line shaped like a structural marker can end text-level
          redaction early. Recorded as strict xfail, not hidden; see docs/OBSERVABILITY.md.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import traceback
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from app.core import redaction
from app.core.logging_setup import JsonFormatter
from app.core.redaction import redact_db_values
from app.core.sentry_config import scrub_event

_URL = os.environ.get("TEST_MIGRATIONS_DATABASE_URL", "")
_NEEDS_PG = pytest.mark.skipif(
    not _URL, reason="needs a real Postgres (TEST_MIGRATIONS_DATABASE_URL)"
)
_SCHEMA = "attack_scratch"

# ----------------------------------------------------------------------------------------------
# payloads
# Must NEVER leak. Names are what shows in a failing test id.
_SAFE_PAYLOADS: dict[str, str] = {
    "plain": "Acme Holdings",
    "double_quote": 'a"b',
    "single_quote": "a'b",
    "quote_bracket": '"]',
    "paren_pair": "a)(b",
    "semicolon_sql": "x'; DROP TABLE t; --",
    "newline": "line1\nline2",
    "blank_line": "para1\n\npara2",
    "two_blank_lines": "para1\n\n\npara2",
    "crlf": "line1\r\nline2",
    "crlf_blank": "para1\r\n\r\npara2",
    "leading_newline": "\nstarts here",
    "trailing_newline": "ends here\n",
    "spaces_only_line": "a\n   \nb",
    "tab": "a\tb",
    "u2028": "a\u2028b",
    "u2029": "a\u2029b",
    "nel_0085": "a\x85b",
    "vt_0b": "a\x0bb",
    "ff_0c": "a\x0cb",
    "fs_1c": "a\x1cb",
    "gs_1d": "a\x1db",
    "rs_1e": "a\x1eb",
    "rail_pipe": "a\n    | b",
    "rail_plus": "a\n  + b",
    "rail_dashes": "a\n  +-+---------------- 1 ----------------\nb",
    "label_detail": "a\nDETAIL:  b",
    "label_context": "a\nCONTEXT:  b",
    "label_hint": "a\nHINT:  b",
    "label_line": "a\nLINE 1: b",
    "unicode": "héllo ✓ 😀 \u202e rtl",
    "format_lookalike": "%s %d {0} ${x} $1 %(a)s",
    "backslashes": "a\\nb\\\\c",
    "many_quote_colon": '": "' * 300,
    "long_line": "x" * 60_000,
    # ordinary client text that merely RESEMBLES structure: a multi-line description must never end
    # redaction
    "natural_labels": (
        "Client: Acme Ltd\nNote: file the GST return\nStatus: pending\nDetail: see attachment"
    ),
    "natural_bullets": (
        "Documents needed:\n  + Bank statements\n  + Form 26AS\n- ledger\n1. PAN card\n* invoices"
    ),
    "natural_file_quote": 'File "GST return.pdf" attached\n  File "TDS.xlsx" also',
    "natural_sql_bracket": "[SQL Server migration]\n[SQL] notes\n(Background on this client: long)",
    "natural_traceback_word": (
        "Traceback of the year's events:\nThe above exception is not relevant"
    ),
    "natural_amounts": "  + 5000\n  - 250\n  +----------\n  + 4750",
    "natural_blank_paragraphs": "Dear team,\n\nPlease file the return.\n\n\nThanks,\nAcme",
    # Unicode line separators used to FAKE line starts. Text is one line as far as Python's
    # traceback is concerned, so a scrubber that splits on more than "\n" would see a forged
    # structure that is not there.
    "u2028_forged_chain": "a\u2028The above exception was the direct cause of "
    "the following exception:\u2028\u2028"
    "Traceback (most recent call last):\u2028b",
    # A value that says "this is an ExceptionGroup traceback" and draws separators: the layout must
    # be decided by something the value cannot forge (round 2, reviewer finding H2).
    "group_header_forged": "a\nException Group Traceback\n  +---------\nb",
    "group_header_plus_forged": (
        "a\n  + Exception Group Traceback (most recent call last):\n"
        "  +-+---------------- 1 ----------------\nb"
    ),
    "group_subexc_forged": (
        "a\nExceptionGroup: x (2 sub-exceptions)\n  +---------------- 2 ----------------\nb"
    ),
    "group_all_railed_forged": (
        "  | Exception Group Traceback\n  | x\n  +---------------- 1 ----------------\n  | y"
    ),
    "group_end_separator_forged": "a\n  +------------------------------------\nb",
    "vt_forged_sql": "a\x0b[SQL: x]\x0bb\x0b(Background on this error at: https://x)\x0bc",
    "nel_forged_label_and_frame": 'a\x85CONTEXT:  x\x85  File "x.py", line 1\x85b',
    # A value with a REAL chain-marker phrase and a REAL blank line after it, but nothing genuine
    # after the blank line: the terminator is only genuine if a Traceback line follows too (pass-2
    # reviewer finding: dropping that third check would end the value right after the blank line
    # and leak this tail).
    "chain_marker_blank_no_traceback": (
        "\nThe above exception was the direct cause of the following exception:"
        "\n\ncontinuation text that must not leak"
    ),
    # The word "sqlalchemy" alone (no ".exc." submodule) plus a forged "[SQL: ...]" line: on a
    # PLAIN psycopg error (never wrapped by SQLAlchemy here), this must NOT be trusted as a genuine
    # SQLAlchemy marker (pass-2 reviewer finding: loosening the "sqlalchemy.exc." check to bare
    # "sqlalchemy" would spuriously trust it and leak everything after).
    "sqlalchemy_word_without_exc_forged_sql": (
        "mentions the sqlalchemy library here\n[SQL: SELECT 1]"
        "\ncontinuation text that must not leak"
    ),
}

# A value that contains a whole line shaped like the STRUCTURE that terminates a DETAIL block. Text
# alone cannot tell it from the real thing; documented as a known limit (req_17), so these are
# strict xfails.
_FORGED_PAYLOADS: dict[str, str] = {
    "forged_sql_line": "a\n[SQL: SELECT 1]\nb",
    "forged_background": "a\n(Background on this error at: https://sqlalche.me/e/20/x)\nb",
    "forged_traceback": "a\nTraceback (most recent call last):\nb",
    "forged_file_frame": 'a\n  File "x.py", line 1, in f\nb',
    "forged_chain_marker": (
        "a\nThe above exception was the direct cause of the following exception:\nb"
    ),
    "forged_error_head": "a\npsycopg.errors.UniqueViolation: x\nb",
}

_KINDS = (
    "unique",
    "notnull",
    "check",
    "fk",
    "int",
    "uuid",
    "date",
    "json",
    "enum",
    # label-less or differently-labelled real shapes (round 2)
    "tz_param",
    "tz_at",
    "plpgsql_exec",
)

# the message template that must survive (P3: still debuggable)
_HEAD = {
    "unique": "duplicate key value violates unique constraint",
    "notnull": "null value in column",
    "check": "violates check constraint",
    "fk": "violates foreign key constraint",
    "int": "invalid input syntax for type integer",
    "uuid": "invalid input syntax for type uuid",
    "date": "invalid input syntax for type date",
    "json": "invalid input syntax for type json",
    "enum": "invalid input value for enum",
    "tz_param": "invalid value for parameter",
    "tz_at": "time zone",
    "plpgsql_exec": "invalid input syntax for type integer",
}
# The label that kind's real Postgres error carries, when it carries one (P3: the label line must
# be redacted-and-KEPT, not silently swallowed as still-inside-the-value; a mutation run (round 2,
# M19) found `test_the_error_stays_debuggable` never checked this for CONTEXT, only the message
# template).
_REAL_LABEL = {
    "unique": "DETAIL",
    "notnull": "DETAIL",
    "check": "DETAIL",
    "fk": "DETAIL",
    "plpgsql_exec": "CONTEXT",
}

_DDL = f"""
DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE;
CREATE SCHEMA {_SCHEMA};
CREATE TYPE {_SCHEMA}.mood AS ENUM ('a', 'b');
CREATE TABLE {_SCHEMA}.t_unique  (id serial PRIMARY KEY, val text UNIQUE);
CREATE TABLE {_SCHEMA}.t_notnull (id serial PRIMARY KEY, a text, b text NOT NULL);
CREATE TABLE {_SCHEMA}.t_check   (id serial PRIMARY KEY, val text CHECK (length(val) < 3));
CREATE TABLE {_SCHEMA}.parent    (k text PRIMARY KEY);
CREATE TABLE {_SCHEMA}.t_fk      (id serial PRIMARY KEY, ref text REFERENCES {_SCHEMA}.parent (k));
CREATE TABLE {_SCHEMA}.t_int     (id serial PRIMARY KEY, n int);
CREATE TABLE {_SCHEMA}.t_uuid    (id serial PRIMARY KEY, u uuid);
CREATE TABLE {_SCHEMA}.t_date    (id serial PRIMARY KEY, d date);
CREATE TABLE {_SCHEMA}.t_json    (id serial PRIMARY KEY, j jsonb);
CREATE TABLE {_SCHEMA}.t_enum    (id serial PRIMARY KEY, e {_SCHEMA}.mood);
CREATE FUNCTION {_SCHEMA}.f_exec(v text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN EXECUTE 'SELECT ' || quote_literal(v) || '::int'; END $$;
"""


def _insert(table: str, columns: str, values: str = "%s") -> str:
    # _SCHEMA and the table/column names are constants in this file; the hostile value is always a
    # bound parameter, never part of the statement text.
    return f"INSERT INTO {_SCHEMA}.{table} ({columns}) VALUES ({values})"  # noqa: S608


_SQL = {
    "unique": _insert("t_unique", "val"),
    "notnull": _insert("t_notnull", "a, b", "%s, NULL"),
    "check": _insert("t_check", "val"),
    "fk": _insert("t_fk", "ref"),
    "int": _insert("t_int", "n"),
    "uuid": _insert("t_uuid", "u"),
    "date": _insert("t_date", "d"),
    "json": _insert("t_json", "j"),
    "enum": _insert("t_enum", "e"),
    # bare messages with no DETAIL/CONTEXT label at all, and QUERY:/LINE echoes from PL/pgSQL
    # EXECUTE
    "tz_param": "SELECT set_config('TimeZone', %s, false)",
    "tz_at": "SELECT now() AT TIME ZONE %s",
    "plpgsql_exec": f"SELECT {_SCHEMA}.f_exec(%s)",
}


def _psycopg_url() -> str:
    return _URL.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture(scope="module")
def conn() -> Iterator[psycopg.Connection[Any]]:
    if not _URL:
        pytest.skip("needs a real Postgres")
    c = psycopg.connect(_psycopg_url(), autocommit=True)
    c.execute(_DDL)  # type: ignore[arg-type]
    yield c
    c.execute(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE")  # type: ignore[arg-type]
    c.close()


def _new_marker() -> str:
    return "MRK" + uuid.uuid4().hex[:12]


def _provoke(c: psycopg.Connection[Any], kind: str, value: str) -> psycopg.Error:
    sql = _SQL[kind]
    try:
        c.execute(sql, (value,))  # type: ignore[arg-type]
        c.execute(sql, (value,))  # type: ignore[arg-type]  # the 2nd insert is the unique violation
    except psycopg.Error as exc:
        return exc
    raise AssertionError(
        f"{kind}: the database accepted the hostile value, so nothing was provoked"
    )


def _chained(c: psycopg.Connection[Any], kind: str, value: str) -> BaseException:
    """A real database error wrapped the way application code wraps it (raise ... from ...)."""
    err = _provoke(c, kind, value)
    try:
        try:
            raise err
        except psycopg.Error as inner:
            raise RuntimeError("could not save the task") from inner
    except RuntimeError as outer:
        return outer


def _skip_if_impossible(kind: str, payload: str) -> None:
    # a btree unique index rejects entries over ~2.7 kB with a different error, which has no echo to
    # test
    if kind == "unique" and len(payload) > 2_000:
        pytest.skip("value too large for a unique index; a different error is raised")


def _value(marker: str, payload: str) -> str:
    return f"{marker}A{payload}{marker}B"


def _assert_no_leak(output: str, marker: str, where: str) -> None:
    for tail in ("A", "B"):
        needle = marker + tail
        if needle in output:
            i = output.index(needle)
            window = output[max(0, i - 60) : i + 60].replace("\n", "\\n")
            pytest.fail(f"LEAK via {where}: {needle} survived, near ...{window}...")


def _record(msg: str, args: tuple[Any, ...], exc: BaseException | None) -> logging.LogRecord:
    exc_info = (type(exc), exc, exc.__traceback__) if exc is not None else None
    return logging.LogRecord("t", logging.ERROR, __file__, 1, msg, args, exc_info)


def _all_safe() -> list[Any]:
    return [pytest.param(k, n, p, id=f"{k}-{n}") for k in _KINDS for n, p in _SAFE_PAYLOADS.items()]


# ------------------------------------------------------------------------- containers, one real
# error each
def _c_text(err: psycopg.Error, outer: BaseException, grouped: BaseException) -> str:
    return redact_db_values(str(err))  # str(exc) exactly as psycopg renders it


def _c_chain(err: psycopg.Error, outer: BaseException, grouped: BaseException) -> str:
    return redact_db_values("".join(traceback.format_exception(outer)))  # raise ... from ...


def _c_group(err: psycopg.Error, outer: BaseException, grouped: BaseException) -> str:
    # an ExceptionGroup traceback prefixes every line with rails such as "  | "
    return redact_db_values("".join(traceback.format_exception(grouped)))


def _c_log_arg(err: psycopg.Error, outer: BaseException, grouped: BaseException) -> str:
    return JsonFormatter().format(
        _record("save failed: %s", (err,), None)
    )  # logger.error("...%s", exc)


def _c_log_exc_chain(err: psycopg.Error, outer: BaseException, grouped: BaseException) -> str:
    return JsonFormatter().format(_record("save failed", (), outer))  # logger.exception(...)


def _c_log_exc_group(err: psycopg.Error, outer: BaseException, grouped: BaseException) -> str:
    return JsonFormatter().format(_record("save failed", (), grouped))


def _c_sentry(err: psycopg.Error, outer: BaseException, grouped: BaseException) -> str:
    event: dict[str, Any] = {
        "exception": {"values": [{"type": type(err).__name__, "value": str(err)}]},
        "logentry": {"message": "save failed: %s", "formatted": f"save failed: {err}"},
        "message": f"save failed: {err}",
        "breadcrumbs": {"values": [{"category": "log", "message": f"save failed: {err}"}]},
    }
    return json.dumps(scrub_event(event, {}), default=str)


def _c_group_raised(err: psycopg.Error, outer: BaseException, grouped: BaseException) -> str:
    try:  # a raised group has a traceback, so it opens with Python's "Exception Group Traceback"
        raise ExceptionGroup("task save failed", [err, ValueError("second member")])
    except ExceptionGroup as caught:
        return redact_db_values("".join(traceback.format_exception(caught)))


def _c_group_with_cause(err: psycopg.Error, outer: BaseException, grouped: BaseException) -> str:
    group = ExceptionGroup("task save failed", [ValueError("second member")])
    group.__cause__ = err  # un-railed cause text, then the chain marker, then the railed group
    return redact_db_values("".join(traceback.format_exception(group)))


_CONTAINERS: dict[str, Callable[[psycopg.Error, BaseException, BaseException], str]] = {
    "text": _c_text,
    "chain": _c_chain,
    "group": _c_group,
    "group_raised": _c_group_raised,
    "group_with_cause": _c_group_with_cause,
    "log_arg": _c_log_arg,
    "log_exc_chain": _c_log_exc_chain,
    "log_exc_group": _c_log_exc_group,
    "sentry": _c_sentry,
}
_LOG_LINES = {"log_arg", "log_exc_chain", "log_exc_group"}


def _leak_check(conn: psycopg.Connection[Any], kind: str, payload: str, container: str) -> None:
    _skip_if_impossible(kind, payload)
    marker = _new_marker()
    value = _value(marker, payload)
    err = _provoke(conn, kind, value)
    outer = _chained(conn, kind, value)
    grouped = ExceptionGroup("task save failed", [err, ValueError("second member")])
    out = _CONTAINERS[container](err, outer, grouped)
    _assert_no_leak(out, marker, container)
    if container in _LOG_LINES:
        assert "\n" not in out and "\r" not in out, (
            f"{container}: the log line is not a single line"
        )
        json.loads(out)  # must stay valid JSON whatever the value contained


@_NEEDS_PG
@pytest.mark.parametrize("container", sorted(_CONTAINERS))
@pytest.mark.parametrize(("kind", "pname", "payload"), _all_safe())
def test_no_container_leaks_a_hostile_value(
    conn: psycopg.Connection[Any], kind: str, pname: str, payload: str, container: str
) -> None:
    _leak_check(conn, kind, payload, container)


@_NEEDS_PG
@pytest.mark.parametrize("kind", _KINDS)
def test_the_error_stays_debuggable(conn: psycopg.Connection[Any], kind: str) -> None:
    """P3. A scrubber that deletes everything passes every leak test; this is what stops that."""
    marker = _new_marker()
    err = _provoke(conn, kind, _value(marker, "x y"))
    outer = _chained(conn, kind, _value(marker, "x y"))
    text_out = redact_db_values("".join(traceback.format_exception(outer)))
    assert type(err).__name__ in text_out, "the exception class name was scrubbed away"
    assert _HEAD[kind] in text_out, f"the message template '{_HEAD[kind]}' was scrubbed away"
    assert 'File "' in text_out and "test_redaction_hostile.py" in text_out, (
        "traceback frames were lost"
    )
    assert "RuntimeError" in text_out, "the wrapping exception's class was lost"
    assert "could not save the task" in text_out, "the wrapper's own (value-free) message was lost"
    label = _REAL_LABEL.get(kind)
    if label is not None:
        assert f"{label}:  [redacted]" in text_out, (
            f"the {label} line was dropped instead of redacted-and-kept: {text_out!r}"
        )


@_NEEDS_PG
@pytest.mark.parametrize("kind", _KINDS)
@pytest.mark.parametrize("raised", [False, True], ids=["never_raised", "raised"])
def test_an_exception_group_keeps_everything_after_the_scrubbed_value(
    conn: psycopg.Connection[Any], kind: str, raised: bool
) -> None:
    """P3 for the group layout. The `+---- 2 ----` separator ends the value, so the NEXT member of
    the group must survive; a scrubber that never recognised the separator would delete it (mutant
    M21 proved that gap). Both layouts: a raised group opens with Python's own "Exception Group
    Traceback" header, a never-raised one with its railed `Name: msg (N sub-exceptions)` line."""
    marker = _new_marker()
    err = _provoke(conn, kind, _value(marker, "x y"))
    grouped = ExceptionGroup("task save failed", [err, ValueError("second member sentinel")])
    if raised:
        try:
            raise grouped
        except ExceptionGroup as caught:
            grouped = caught
    cleaned = redact_db_values("".join(traceback.format_exception(grouped)))
    _assert_no_leak(cleaned, marker, "group")
    assert _HEAD[kind] in cleaned, "the first member's message template was scrubbed away"
    assert "ValueError: second member sentinel" in cleaned, (
        "the group's second member was swallowed by the scrubber"
    )
    assert "ExceptionGroup: task save failed (2 sub-exceptions)" in cleaned, (
        "the group's own line was lost"
    )


@_NEEDS_PG
def test_golden_a_real_unique_violation_keeps_everything_but_the_value(
    conn: psycopg.Connection[Any],
) -> None:
    """The exact expected text, written by hand from what a reviewer would call correct: the value
    is gone and
    every other byte of Postgres's message is untouched."""
    marker = _new_marker()
    err = _provoke(conn, "unique", marker + "Acme Holdings")
    assert marker in str(err), (
        "guard: the real error no longer echoes the value, so this test proves nothing"
    )
    assert redact_db_values(str(err)) == (
        'duplicate key value violates unique constraint "t_unique_val_key"\nDETAIL:  [redacted]'
    )


@pytest.mark.parametrize(
    "value", ["'{m}'::int", "{m}\nsecond line of the statement", '"{m}" ; DROP TABLE x -- \'']
)
def test_a_query_line_is_redacted_even_with_no_line_label_before_it(value: str) -> None:
    """R5 (mutation) found that no real Postgres 17 shape needs the `QUERY:` label on its own: in
    every one provoked (tests above, pgshapes probe) it sits under a `LINE n:` line whose skip
    already swallows it. It stays as defence in depth (a missed label leaks, an extra one only
    over-redacts), so this hand-built text pins that it works by itself."""
    marker = _new_marker()
    query = value.replace("{m}", marker)
    cleaned = redact_db_values(
        "psycopg.errors.InternalError: boom\n"
        f"QUERY:  SELECT {query}\n"
        "CONTEXT:  PL/pgSQL function f(text) line 1 at EXECUTE"
    )
    assert marker not in cleaned, f"a QUERY: line leaked the statement: {cleaned!r}"
    assert cleaned.startswith("psycopg.errors.InternalError: boom\nQUERY:  [redacted]"), cleaned


@_NEEDS_PG
@pytest.mark.parametrize("hide", [True, False], ids=["hide_params", "show_params"])
def test_golden_a_real_sqlalchemy_unique_violation(hide: bool) -> None:
    marker = _new_marker()
    engine = create_engine(_URL, hide_parameters=hide)
    sql = text(_insert("t_unique", "val", ":v"))
    try:
        with (
            engine.connect().execution_options(isolation_level="AUTOCOMMIT") as sa,
            pytest.raises(DBAPIError) as info,
        ):
            sa.execute(sql, {"v": marker + "Acme Holdings"})
            sa.execute(sql, {"v": marker + "Acme Holdings"})
    finally:
        engine.dispose()
    assert marker in str(info.value), (
        "guard: the real error no longer echoes the value, so this test proves nothing"
    )
    parameters = (
        "[SQL parameters hidden due to hide_parameters=True]"
        if hide
        else "[parameters: [redacted]]"
    )
    expected = (
        "(psycopg.errors.UniqueViolation) duplicate key value violates "
        'unique constraint "t_unique_val_key"\n'
        "DETAIL:  [redacted]\n"
        f"[SQL: {_insert('t_unique', 'val', '%(v)s')}]\n"
        f"{parameters}\n"
        "(Background on this error at: https://sqlalche.me/e/20/gkpj)"
    )
    assert redact_db_values(str(info.value)) == expected


@_NEEDS_PG
def test_a_numeric_out_of_range_echo_is_scrubbed(conn: psycopg.Connection[Any]) -> None:
    """`value "<the number>" is out of range for type smallint`: the value is mid-sentence."""
    number = "73914628"
    with pytest.raises(psycopg.Error) as info:
        conn.execute("SELECT %s::smallint", (number,))
    assert number in str(info.value), (
        "guard: the real error no longer echoes the value, so this test proves nothing"
    )
    assert number not in redact_db_values(str(info.value))
    grouped = "".join(traceback.format_exception(ExceptionGroup("g", [info.value])))
    assert number not in redact_db_values(grouped)


@_NEEDS_PG
@pytest.mark.parametrize("pname", ["plain", "single_quote", "newline", "blank_line", "unicode"])
def test_an_inline_literal_echoed_after_LINE_is_scrubbed(
    conn: psycopg.Connection[Any], pname: str
) -> None:
    """A statement with an inline literal makes Postgres print `LINE 1: SELECT '<value>'::int`."""
    marker = _new_marker()
    literal = _value(marker, _SAFE_PAYLOADS[pname]).replace("'", "''")
    with pytest.raises(psycopg.Error) as info:
        # deliberate: the test needs Postgres to echo an inline literal in its LINE excerpt
        conn.execute(f"SELECT '{literal}'::int")  # type: ignore[arg-type]
    raw = str(info.value)
    assert "LINE 1:" in raw, (
        "guard: the real error no longer has a LINE echo, so this test proves nothing"
    )
    cleaned = redact_db_values(raw)
    _assert_no_leak(cleaned, marker, "LINE echo")
    # P3 (debuggability): the LINE line must be REDACTED and kept, not silently dropped. Without
    # `_label_of` recognising it, the line is treated as still inside the value from the message
    # head's own scrub and vanishes with no leak either way — a mutation run found that shape of
    # gap (round 2, M17): a security test alone cannot see it, only a content assertion can.
    assert "LINE 1:  [redacted]" in cleaned, (
        f"the LINE echo was dropped instead of redacted-and-kept: {cleaned!r}"
    )
    _assert_no_leak(
        JsonFormatter().format(_record("bad literal: %s", (info.value,), None)), marker, "log arg"
    )


_SA_PAYLOADS = (
    "blank_line",
    "quote_bracket",
    "crlf_blank",
    "rail_dashes",
    "natural_labels",
    "natural_bullets",
    "natural_sql_bracket",
    "unicode",
    *_FORGED_PAYLOADS,
)


@_NEEDS_PG
@pytest.mark.parametrize("hide", [True, False], ids=["hide_params", "show_params"])
@pytest.mark.parametrize("pname", _SA_PAYLOADS)
@pytest.mark.parametrize("kind", _KINDS)
def test_a_sqlalchemy_wrapped_error_is_scrubbed(kind: str, pname: str, hide: bool) -> None:
    """SQLAlchemy adds its own structure ([SQL: ...], [parameters: ...], the Background line), and
    with
    hide_parameters off it prints the bound value itself. Real exceptions, forged and natural
    payloads."""
    payload = {**_SAFE_PAYLOADS, **_FORGED_PAYLOADS}[pname]
    _skip_if_impossible(kind, payload)
    marker = _new_marker()
    value = _value(marker, payload)
    sql = _SQL[kind].replace("%s", ":v")
    engine = create_engine(_URL, hide_parameters=hide)
    try:
        with (
            engine.connect().execution_options(isolation_level="AUTOCOMMIT") as sa,
            pytest.raises(DBAPIError) as info,
        ):
            sa.execute(text(sql), {"v": value})
            sa.execute(text(sql), {"v": value})  # the 2nd insert is the unique violation
    finally:
        engine.dispose()
    exc = info.value
    cleaned = redact_db_values(str(exc))
    _assert_no_leak(cleaned, marker, f"SQLAlchemy str(exc) hide={hide}")
    _assert_no_leak(
        JsonFormatter().format(_record("db failed", (), exc)), marker, f"JsonFormatter hide={hide}"
    )
    group = ExceptionGroup("g", [exc])
    _assert_no_leak(
        JsonFormatter().format(_record("db failed", (), group)), marker, "JsonFormatter group"
    )
    assert type(exc).__name__ in cleaned or "psycopg" in cleaned, (
        "the error lost its own and the driver's class name"
    )
    # P3: SQLAlchemy's own debugging lines are not client data and must survive (a scrubber that
    # swallowed the statement after the value would pass every leak check above; mutant M07 proved
    # that gap).
    assert "\n[SQL: " in cleaned, "the [SQL: ...] statement line was scrubbed away"
    assert "\n(Background on this error at:" in cleaned, "the Background line was scrubbed away"
    hidden_or_redacted = "[SQL parameters hidden" if hide else "[parameters: [redacted]]"
    assert hidden_or_redacted in cleaned, (
        f"expected the parameters line to read '{hidden_or_redacted}'"
    )


# ----------------------------------------------------------------------------- known limit
# (req_17): xfail
_FORGED_KINDS = ("unique", "int", "json")


@_NEEDS_PG
@pytest.mark.parametrize(
    ("kind", "pname", "payload"),
    [
        pytest.param(k, n, p, id=f"{k}-{n}")
        for k in _FORGED_KINDS
        for n, p in _FORGED_PAYLOADS.items()
    ],
)
def test_a_value_that_forges_structure_does_not_end_redaction_early(
    conn: psycopg.Connection[Any], kind: str, pname: str, payload: str
) -> None:
    """req_17. Requirement first: it must not leak. Any case the text-level design provably cannot
    close is
    marked xfail(strict) with the reason AFTER the fix has been tried, not guessed in advance."""
    marker = _new_marker()
    err = _provoke(conn, kind, _value(marker, payload))
    _assert_no_leak(redact_db_values(str(err)), marker, "forged structural line")


@_NEEDS_PG
@pytest.mark.xfail(
    strict=True,
    reason="KNOWN LIMIT (req_17, root cause D): a client value that reproduces a WHOLE genuine "
    "terminator (chain marker + blank line + Traceback line) is indistinguishable from the real "
    "one in text. The complete fix is to render exceptions from the exception object "
    "(deferred). See docs/OBSERVABILITY.md.",
)
def test_a_value_that_forges_a_complete_chain_marker_is_the_known_limit(
    conn: psycopg.Connection[Any],
) -> None:
    forged = (
        "a\nThe above exception was the direct cause of the following exception:\n\n"
        "Traceback (most recent call last):\nb"
    )
    marker = _new_marker()
    err = _provoke(conn, "unique", _value(marker, forged))
    _assert_no_leak(redact_db_values(str(err)), marker, "complete forged chain marker")


# ------------------------------------------------------------------------------------------- time
# / bounds
def _t(fn: Callable[[], object]) -> float:
    best = float("inf")
    for _ in range(3):
        t0 = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - t0)
    return best


_SHAPES: dict[str, Callable[[int], str]] = {
    "repeated_colon_quote": lambda n: "psycopg " + ': "a' * n,
    "repeated_detail_lines": lambda n: "psycopg\n" + "DETAIL:  x\n" * n,
    "many_blank_lines": lambda n: "psycopg\nDETAIL:  x\n" + "\n" * n,
    "repeated_sql_marker": lambda n: "psycopg\nDETAIL:  x\n" + "[SQL:" * n,
    "rail_prefix_run": lambda n: "psycopg\n" + "| " * n + "DETAIL:  x",
    "one_long_line": lambda n: "psycopg " + "a" * n,
    "detail_then_long_value": lambda n: "psycopg\nDETAIL:  " + "x\n" * n,
    "quote_run": lambda n: 'psycopg: "' + '"' * n,
    "head_lines_with_quotes": lambda n: "psycopg.errors.X: a" + ': "b\n' * n,
}


@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_redaction_time_is_linear_not_quadratic(shape: str) -> None:
    build = _SHAPES[shape]
    small, big = build(3_000), build(24_000)  # 8x the input
    t_small = max(_t(lambda: redact_db_values(small)), 1e-4)
    t_big = _t(lambda: redact_db_values(big))
    assert t_big < 25 * t_small + 0.05, (
        f"{shape}: 8x the input took {t_big / t_small:.0f}x the time (quadratic would be ~64x)"
    )


@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_huge_hostile_input_finishes_quickly_and_the_work_is_bounded(shape: str) -> None:
    build = _SHAPES[shape]
    huge = build(400_000)  # far above any real log line
    t0 = time.perf_counter()
    out = redact_db_values(huge)
    elapsed = time.perf_counter() - t0
    assert elapsed < 2.0, (
        f"{shape}: {len(huge)} chars took {elapsed:.1f}s (an event-loop stall in a log handler)"
    )
    assert len(out) <= 200_000, f"{shape}: output not bounded ({len(out)} chars)"


def test_a_failing_redactor_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """ASVS 16.5.3: never fail open. Whatever goes wrong inside, the raw text must not come out."""
    secret = "MRK-SECRET-must-not-escape"
    text_in = f'psycopg.errors.X: invalid input syntax: "{secret}"'

    def boom(_: str) -> str:
        raise RuntimeError("internal failure")

    monkeypatch.setattr(redaction, "_redact_db_error_text", boom, raising=True)
    out = redact_db_values(text_in)
    assert secret not in out
    assert out, "a failed redaction should leave a visible placeholder, not an empty string"


@pytest.mark.parametrize(
    "not_text", [None, 5, b"MRK-SECRET", ValueError("MRK-SECRET"), ["MRK-SECRET"]]
)
def test_a_non_string_argument_fails_closed_and_never_echoes_itself(not_text: object) -> None:
    """A caller can pass the wrong type: the answer is the placeholder, never `str(arg)`."""
    out = redact_db_values(not_text)  # type: ignore[arg-type]
    assert "MRK-SECRET" not in out
    assert out == "[exception text withheld: redaction failed]"


# --------------------------------------------------------------------------- P4: untouched /
# idempotent / safe
_ORDINARY = [
    "",
    'plain sentence with a colon: and a quote " inside',
    "ValueError: invalid literal for int() with base 10: 'abc'",
    'KeyError: "missing"',
    'Traceback (most recent call last):\n  File "a.py", line 1, in f\nValueError: boom',
    "see DETAIL: not at the start of a line",
    'a: "b" c: "d"',
    "user@example.com logged in",
]


@pytest.mark.parametrize("ordinary", _ORDINARY)
def test_text_that_is_not_a_database_error_is_untouched(ordinary: str) -> None:
    assert redact_db_values(ordinary) == ordinary


_WEIRD = [
    "",
    "\x00",
    "\ud800",
    "\n" * 5,
    "psycopg",
    "psycopg\nDETAIL:  ",
    "DETAIL:  ",
    "|",
    "  | ",
    "\r",
    "\u2028" * 4,
]


@pytest.mark.parametrize("weird", _WEIRD)
def test_redaction_never_raises_and_is_idempotent(weird: str) -> None:
    once = redact_db_values(weird)
    assert redact_db_values(once) == once


@_NEEDS_PG
@pytest.mark.parametrize("kind", _KINDS)
def test_redaction_is_idempotent_on_real_errors(conn: psycopg.Connection[Any], kind: str) -> None:
    err = _provoke(conn, kind, _value(_new_marker(), 'a\n\nb "c"'))
    once = redact_db_values("".join(traceback.format_exception(ExceptionGroup("g", [err]))))
    assert redact_db_values(once) == once


# ------------------------------------------------------------------ req_13: no new sink formats
# exceptions
_ALLOWED = {Path("app/core/logging_setup.py"), Path("app/core/redaction.py")}
_SINK_TOKENS = re.compile(r"formatException\(|traceback\.format_|format_exc\(|print_exc\(")


def test_no_module_formats_exception_text_outside_the_redacted_choke_point() -> None:
    """Root cause (E): a convention with no enforcement. A new module that formats a traceback by
    itself would
    bypass the redactor silently; this makes that a failing test instead."""
    root = Path(__file__).resolve().parents[2]
    offenders = []
    for path in (root / "app").rglob("*.py"):
        rel = path.relative_to(root)
        if rel in _ALLOWED:
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _SINK_TOKENS.search(line) and not line.lstrip().startswith("#"):
                offenders.append(f"{rel}:{n}: {line.strip()}")
    assert not offenders, (
        "exception text is formatted outside the redacted choke point:\n" + "\n".join(offenders)
    )
