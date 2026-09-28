"""ops/db_check.py: threshold boundaries, fail-closed exits, no credential/tenant-data leakage and —
against a real Postgres — that the `ops_monitor` role it runs as really can't read or write tenant
data (migration 66bc34819e6a). The privilege claims in that migration are only worth what this
proves; a mock can't grant or refuse anything.

Real-Postgres tests skip locally unless TEST_MIGRATIONS_DATABASE_URL is set (CI does).
"""

# These tests deliberately read the module's private query constants and _database_url: pinning the
# exact SQL the tool may run is the point (see the structural tests below).
# pyright: reportPrivateUsage=false

import os
import re
import secrets
from collections.abc import Callable, Generator, Sequence
from contextlib import AbstractContextManager, nullcontext
from typing import Any

import psycopg
import pytest
from psycopg import sql as pgsql
from sqlalchemy.engine import make_url

from ops import db_check
from ops.db_check import Finding, SlowStatement, Snapshot, Thresholds

_MIGRATIONS_URL = os.environ.get("TEST_MIGRATIONS_DATABASE_URL")
_NEEDS_PG = pytest.mark.skipif(
    not _MIGRATIONS_URL, reason="needs a real Postgres — TEST_MIGRATIONS_DATABASE_URL (CI does)"
)

_T = Thresholds()


def _snap(**overrides: Any) -> Snapshot:
    base: dict[str, Any] = {
        "max_connections": 100,
        "total_sessions": 10,
        "idle_in_tx": 0,
        "long_running": 0,
        "blocked": 0,
        "slow_statements": [],
        "statements_available": True,
        "dead_tables": [],
        "table_rows": {},
    }
    return Snapshot(**{**base, **overrides})


def _checks(findings: Sequence[Finding]) -> list[str]:
    return [f.check for f in findings]


# ------------------------------------------------------------------ evaluate(): pure boundaries


def test_a_healthy_snapshot_has_no_findings() -> None:
    assert db_check.evaluate(_snap(), _T) == []


@pytest.mark.parametrize(
    ("sessions", "expected"),
    [(69, False), (70, True), (71, True), (100, True)],
)
def test_connection_headroom_boundary(sessions: int, expected: bool) -> None:
    findings = db_check.evaluate(_snap(total_sessions=sessions, max_connections=100), _T)
    assert (_checks(findings) == ["connections"]) is expected
    assert (findings == []) is (not expected)


def test_connection_finding_reports_counts_not_a_bare_flag() -> None:
    (finding,) = db_check.evaluate(_snap(total_sessions=42, max_connections=60), _T)
    assert "42" in finding.detail
    assert "60" in finding.detail


@pytest.mark.parametrize("max_connections", [0, -1])
def test_a_nonsense_max_connections_never_divides_by_zero(max_connections: int) -> None:
    assert db_check.evaluate(_snap(max_connections=max_connections, total_sessions=5), _T) == []


@pytest.mark.parametrize(
    ("field_name", "check"),
    [
        ("idle_in_tx", "idle_in_transaction"),
        ("long_running", "long_running_queries"),
        ("blocked", "lock_waits"),
    ],
)
def test_counted_session_findings_fire_at_one_and_not_at_zero(field_name: str, check: str) -> None:
    assert db_check.evaluate(_snap(**{field_name: 0}), _T) == []
    assert _checks(db_check.evaluate(_snap(**{field_name: 1}), _T)) == [check]
    (finding,) = db_check.evaluate(_snap(**{field_name: 7}), _T)
    assert "7" in finding.detail


def test_missing_pg_stat_statements_is_a_finding_not_a_silent_skip() -> None:
    findings = db_check.evaluate(_snap(statements_available=False), _T)
    assert _checks(findings) == ["pg_stat_statements"]


def test_slow_statements_are_reported_by_query_id_only() -> None:
    slow = [SlowStatement(queryid="-123456789", mean_ms=812.4, calls=90)]
    (finding,) = db_check.evaluate(_snap(slow_statements=slow), _T)
    assert finding.check == "slow_statement"
    assert "-123456789" in finding.detail
    assert "812" in finding.detail
    assert "90" in finding.detail


def test_vacuum_lag_names_the_table_and_counts() -> None:
    (finding,) = db_check.evaluate(_snap(dead_tables=[("tasks", 50_000, 100_000)]), _T)
    assert finding.check == "vacuum_lag"
    assert "tasks" in finding.detail
    assert "50000" in finding.detail


@pytest.mark.parametrize(("rows", "expected"), [(999_999, False), (1_000_000, True)])
def test_table_growth_boundary(rows: int, expected: bool) -> None:
    findings = db_check.evaluate(_snap(table_rows={"notifications": rows}), _T)
    assert (_checks(findings) == ["table_growth"]) is expected
    assert (findings == []) is (not expected)


def test_table_growth_ignores_tables_it_has_no_limit_for() -> None:
    assert db_check.evaluate(_snap(table_rows={"some_other_table": 10**9}), _T) == []


def test_every_default_growth_limit_is_a_positive_int() -> None:
    limits = Thresholds().table_row_limits
    assert limits
    assert all(isinstance(v, int) and v > 0 for v in limits.values())


def test_multiple_problems_are_all_reported_not_just_the_first() -> None:
    snap = _snap(total_sessions=90, idle_in_tx=2, blocked=1, statements_available=False)
    assert set(_checks(db_check.evaluate(snap, _T))) == {
        "connections",
        "idle_in_transaction",
        "lock_waits",
        "pg_stat_statements",
    }


# ------------------------------------------------------------------ collect(): SQL + parameters


class _Cursor:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows


Responder = Callable[[str, tuple[Any, ...]], list[tuple[Any, ...]]]


class _FakeConn:
    def __init__(self, responder: Responder) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self._responder = responder

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _Cursor:
        self.calls.append((sql, tuple(params)))
        return _Cursor(self._responder(sql, tuple(params)))


def _healthy_responder(sql: str, params: tuple[Any, ...]) -> list[tuple[Any, ...]]:
    if sql == db_check._MAX_CONNECTIONS:
        return [(60,)]
    if sql == db_check._TOTAL_SESSIONS:
        return [(12,)]
    if sql in (db_check._IDLE_IN_TX, db_check._LONG_RUNNING, db_check._BLOCKED):
        return [(0,)]
    return []


def test_collect_reads_every_registered_query_and_passes_thresholds_as_parameters() -> None:
    conn = _FakeConn(_healthy_responder)
    snap = db_check.collect(conn, _T)  # type: ignore[arg-type]
    assert snap.max_connections == 60
    assert snap.total_sessions == 12
    assert snap.statements_available is True
    assert {sql for sql, _ in conn.calls} == set(db_check.ALL_QUERIES)
    by_sql = dict(conn.calls)
    assert by_sql[db_check._IDLE_IN_TX] == (_T.idle_in_tx_seconds,)
    assert by_sql[db_check._LONG_RUNNING] == (_T.long_running_seconds,)
    assert by_sql[db_check._BLOCKED] == (_T.blocked_seconds,)
    assert by_sql[db_check._SLOW_STATEMENTS] == (_T.slow_statement_min_calls, _T.slow_statement_ms)
    assert by_sql[db_check._DEAD_TUPLES] == (_T.dead_tuple_min, _T.dead_tuple_ratio)
    assert by_sql[db_check._TABLE_ROWS] == (list(_T.table_row_limits),)


def test_collect_maps_rows_into_the_snapshot() -> None:
    def responder(sql: str, params: tuple[Any, ...]) -> list[tuple[Any, ...]]:
        if sql == db_check._SLOW_STATEMENTS:
            return [(-42, 900.5, 77)]
        if sql == db_check._DEAD_TUPLES:
            return [("tasks", 30_000, 90_000)]
        if sql == db_check._TABLE_ROWS:
            return [("notifications", 1_500_000)]
        return _healthy_responder(sql, params)

    snap = db_check.collect(_FakeConn(responder), _T)  # type: ignore[arg-type]
    assert snap.slow_statements == [SlowStatement("-42", 900.5, 77)]
    assert snap.dead_tables == [("tasks", 30_000, 90_000)]
    assert snap.table_rows == {"notifications": 1_500_000}


def test_a_missing_statements_extension_becomes_a_gap_not_a_crash() -> None:
    def responder(sql: str, params: tuple[Any, ...]) -> list[tuple[Any, ...]]:
        if sql == db_check._SLOW_STATEMENTS:
            raise psycopg.errors.UndefinedTable("relation pg_stat_statements does not exist")
        return _healthy_responder(sql, params)

    snap = db_check.collect(_FakeConn(responder), _T)  # type: ignore[arg-type]
    assert snap.statements_available is False
    assert snap.slow_statements == []


def test_any_other_query_failure_propagates_so_main_can_fail_closed() -> None:
    def responder(sql: str, params: tuple[Any, ...]) -> list[tuple[Any, ...]]:
        if sql == db_check._TOTAL_SESSIONS:
            raise psycopg.errors.InsufficientPrivilege("nope")
        return _healthy_responder(sql, params)

    with pytest.raises(psycopg.Error):
        db_check.collect(_FakeConn(responder), _T)  # type: ignore[arg-type]


# ------------------------------------------------------------------ structural: what may be read

_ALLOWED_RELATIONS = {"pg_stat_activity", "pg_stat_statements", "pg_stat_user_tables"}
_RELATION = re.compile(r"\b(?:from|join)\s+([\w.\"]+)", re.IGNORECASE)


def _query_constants() -> dict[str, str]:
    return {
        name: value
        for name, value in vars(db_check).items()
        if name.startswith("_")
        and isinstance(value, str)
        and value.lstrip().upper().startswith("SELECT")
    }


def test_every_query_constant_is_registered_in_all_queries() -> None:
    # A query added but not listed would dodge the structural checks below.
    constants = _query_constants()
    assert len(constants) >= 8
    assert set(constants.values()) == set(db_check.ALL_QUERIES)


def test_queries_only_name_statistics_views_never_a_tenant_table() -> None:
    for sql in db_check.ALL_QUERIES:
        relations = {r.lower().removeprefix("pg_catalog.") for r in _RELATION.findall(sql)}
        assert relations <= _ALLOWED_RELATIONS, f"unexpected relation(s) in: {sql}"


def test_queries_never_select_sql_text_or_other_row_data() -> None:
    # `query` (pg_stat_activity / pg_stat_statements) can contain literal values from other
    # sessions; this tool reports counts and query IDs only.
    for sql in db_check.ALL_QUERIES:
        assert not re.search(r"\bquery\b", sql, re.IGNORECASE), sql
        assert not re.search(r"\b(usename|client_addr|application_name|datname)\b", sql), sql
        assert "*" not in sql.replace("count(*)", ""), sql


def test_queries_are_static_and_parameterized_never_interpolated() -> None:
    for sql in db_check.ALL_QUERIES:
        assert "{" not in sql
        assert "'%" not in sql
        assert not re.search(r"\b\d{2,}\b", re.sub(r"'[^']*'", "", sql)), f"inline number: {sql}"


def test_the_module_never_issues_a_write_or_ddl_statement() -> None:
    forbidden = re.compile(
        r"\b(insert|update|delete|drop|alter|create|truncate|grant|copy)\b", re.I
    )
    for sql in db_check.ALL_QUERIES:
        assert not forbidden.search(sql), sql


# ------------------------------------------------------------------ _database_url()

_PW = "S3cr3t" + "PW"  # split so a secret scanner doesn't flag a fake credential literal


def _set_url(monkeypatch: pytest.MonkeyPatch, url: str | None) -> None:
    if url is None:
        monkeypatch.delenv("OPS_MONITOR_DATABASE_URL", raising=False)
    else:
        monkeypatch.setenv("OPS_MONITOR_DATABASE_URL", url)


def test_url_from_env_normalizes_the_driver_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_url(monkeypatch, f"postgresql+psycopg://u:{_PW}@localhost:5432/postgres")
    assert db_check._database_url() == f"postgresql://u:{_PW}@localhost:5432/postgres"


def test_loopback_needs_no_tls_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_url(monkeypatch, f"postgresql://u:{_PW}@127.0.0.1:5432/postgres")
    db_check._database_url()


def test_remote_host_with_verify_full_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_url(monkeypatch, f"postgresql://u:{_PW}@db.example.com:5432/postgres?sslmode=verify-full")
    db_check._database_url()


@pytest.mark.parametrize(
    "suffix", ["", "?sslmode=require", "?sslmode=prefer", "?sslmode=disable", "?sslmode=verify-ca"]
)
def test_remote_host_without_verify_full_is_refused(
    monkeypatch: pytest.MonkeyPatch, suffix: str
) -> None:
    _set_url(monkeypatch, f"postgresql://u:{_PW}@db.example.com:5432/postgres{suffix}")
    with pytest.raises(ValueError, match="verify-full"):
        db_check._database_url()


def test_a_remote_second_host_in_a_failover_url_is_still_caught(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_url(monkeypatch, f"postgresql://u:{_PW}@localhost:5432,db.example.com:5432/postgres")
    with pytest.raises(ValueError):
        db_check._database_url()


@pytest.mark.parametrize("bad", [None, "", "not a url", "mysql://u:p@localhost/db", "http://x"])
def test_missing_or_non_postgres_url_is_refused(
    monkeypatch: pytest.MonkeyPatch, bad: str | None
) -> None:
    _set_url(monkeypatch, bad)
    with pytest.raises(ValueError):
        db_check._database_url()


def test_url_errors_never_echo_the_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_url(monkeypatch, f"mysql://u:{_PW}@localhost/db")
    with pytest.raises(ValueError) as caught:
        db_check._database_url()
    assert _PW not in str(caught.value)
    _set_url(monkeypatch, f"postgresql://u:{_PW}@db.example.com/postgres?sslmode=require")
    with pytest.raises(ValueError) as caught:
        db_check._database_url()
    assert _PW not in str(caught.value)


# ------------------------------------------------------------------ main(): exit codes, output


def _fake_connect(
    monkeypatch: pytest.MonkeyPatch,
    *,
    snapshot: Snapshot | None = None,
    error: Exception | None = None,
) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []

    def connect(url: str, **kwargs: Any) -> AbstractContextManager[object]:
        seen.append({"url": url, **kwargs})
        if error is not None:
            raise error
        return nullcontext(object())

    monkeypatch.setattr(db_check.psycopg, "connect", connect)
    if snapshot is not None:
        monkeypatch.setattr(db_check, "collect", lambda conn, thresholds: snapshot)
    return seen


def _local_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_url(monkeypatch, f"postgresql://ops_monitor:{_PW}@localhost:5432/postgres")


def test_main_exits_2_and_says_nothing_secret_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _set_url(monkeypatch, None)
    seen = _fake_connect(monkeypatch)
    assert db_check.main() == 2
    out = capsys.readouterr()
    assert "OPS_MONITOR_DATABASE_URL" in out.err
    assert seen == []  # never even attempted a connection


def test_main_exits_2_for_a_remote_url_without_verify_full_and_never_connects(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _set_url(monkeypatch, f"postgresql://ops_monitor:{_PW}@db.example.com:5432/postgres")
    seen = _fake_connect(monkeypatch)
    assert db_check.main() == 2
    out = capsys.readouterr()
    combined = out.out + out.err
    assert _PW not in combined
    assert "db.example.com" not in combined
    assert seen == []


def test_main_exits_0_and_prints_ok_when_healthy(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _local_url(monkeypatch)
    seen = _fake_connect(monkeypatch, snapshot=_snap(total_sessions=12, max_connections=60))
    assert db_check.main() == 0
    out = capsys.readouterr().out
    assert "ops db-check: OK" in out
    assert "connections 12/60" in out
    assert "FINDING" not in out
    assert _PW not in out
    (call,) = seen
    assert call["autocommit"] is True
    assert call["prepare_threshold"] is None  # the shared pooler can't do prepared statements
    assert call["connect_timeout"] == 10


def test_main_exits_1_and_lists_every_finding(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _local_url(monkeypatch)
    _fake_connect(monkeypatch, snapshot=_snap(total_sessions=58, max_connections=60, blocked=2))
    assert db_check.main() == 1
    out = capsys.readouterr().out
    assert "FINDING connections:" in out
    assert "FINDING lock_waits:" in out
    assert "ops db-check: FAILED" in out
    assert "ops db-check: OK" not in out


def test_main_fails_closed_when_the_database_is_unreachable_and_leaks_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _local_url(monkeypatch)
    leaky = psycopg.OperationalError(f"connection to server at db.internal failed: password {_PW}")
    _fake_connect(monkeypatch, error=leaky)
    assert db_check.main() == 1
    out = capsys.readouterr()
    combined = out.out + out.err
    assert "OperationalError" in combined
    assert _PW not in combined
    assert "db.internal" not in combined
    assert "OK" not in combined


def test_main_fails_closed_when_a_query_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _local_url(monkeypatch)
    _fake_connect(monkeypatch)

    def refuse(conn: object, thresholds: Thresholds) -> Snapshot:
        raise psycopg.errors.InsufficientPrivilege("permission denied")

    monkeypatch.setattr(db_check, "collect", refuse)
    assert db_check.main() == 1
    out = capsys.readouterr()
    assert "OK" not in out.out + out.err


# ------------------------------------------------------------------ real Postgres, as ops_monitor


def _admin() -> "psycopg.Connection[Any]":
    assert _MIGRATIONS_URL is not None
    return psycopg.connect(
        make_url(_MIGRATIONS_URL)
        .set(drivername="postgresql")
        .render_as_string(hide_password=False),
        autocommit=True,
    )


@pytest.fixture
def ops_url() -> Generator[str]:
    """A URL for the real `ops_monitor` role. The migration deliberately sets no password, so this
    sets a throwaway one for the test and clears it afterwards (the container is disposable, and
    clearing it means a leftover can never authenticate).
    """
    assert _MIGRATIONS_URL is not None
    password = secrets.token_urlsafe(24)
    with _admin() as admin:
        admin.execute(
            pgsql.SQL("ALTER ROLE ops_monitor WITH PASSWORD {}").format(pgsql.Literal(password))
        )
    try:
        yield (
            make_url(_MIGRATIONS_URL)
            .set(drivername="postgresql", username="ops_monitor", password=password)
            .render_as_string(hide_password=False)
        )
    finally:
        with _admin() as admin:
            admin.execute("ALTER ROLE ops_monitor WITH PASSWORD NULL")


@_NEEDS_PG
def test_role_attributes_are_least_privilege() -> None:
    with _admin() as admin:
        row = admin.execute(
            "SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb, rolreplication, "
            "rolcanlogin, rolconnlimit FROM pg_roles WHERE rolname = 'ops_monitor'"
        ).fetchone()
        assert row == (False, False, False, False, False, True, 2)
        memberships = admin.execute(
            "SELECT g.rolname FROM pg_auth_members m JOIN pg_roles g ON g.oid = m.roleid "
            "JOIN pg_roles r ON r.oid = m.member WHERE r.rolname = 'ops_monitor'"
        ).fetchall()
        assert {name for (name,) in memberships} == {"pg_monitor"}


@_NEEDS_PG
def test_the_migration_left_the_role_without_a_password() -> None:
    with _admin() as admin:
        row = admin.execute(
            "SELECT rolpassword IS NULL FROM pg_authid WHERE rolname = 'ops_monitor'"
        ).fetchone()
    assert row == (True,)


@_NEEDS_PG
def test_role_has_bounded_read_only_session_defaults(ops_url: str) -> None:
    with psycopg.connect(ops_url, autocommit=True) as conn:
        assert conn.execute("SHOW default_transaction_read_only").fetchone() == ("on",)
        assert conn.execute("SHOW statement_timeout").fetchone() == ("10s",)
        assert conn.execute("SHOW idle_in_transaction_session_timeout").fetchone() == ("30s",)
        assert conn.execute("SHOW lock_timeout").fetchone() == ("2s",)


@_NEEDS_PG
def test_role_cannot_read_any_tenant_table(ops_url: str) -> None:
    with _admin() as admin:
        tables = [
            name
            for (name,) in admin.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                "AND tablename <> 'alembic_version'"
            ).fetchall()
        ]
    assert {"firms", "profiles", "tasks", "notifications", "issues"} <= set(tables)
    with psycopg.connect(ops_url, autocommit=True) as conn:
        for table in tables:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(
                    pgsql.SQL("SELECT 1 FROM public.{} LIMIT 1").format(pgsql.Identifier(table))
                )


@_NEEDS_PG
def test_role_holds_no_privilege_of_any_kind_on_any_relation() -> None:
    # Catalog-level, so it doesn't depend on RLS or the read-only default happening to refuse a
    # particular statement (negative control P3: a granted INSERT was still refused by RLS).
    with _admin() as admin:
        rows = admin.execute(
            "SELECT c.relname, p FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "CROSS JOIN unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES',"
            "'TRIGGER']) AS p WHERE n.nspname = 'public' AND c.relkind IN ('r','p','v','m','S') "
            "AND has_table_privilege('ops_monitor', c.oid, p)"
        ).fetchall()
    assert rows == []


@_NEEDS_PG
def test_role_lacks_write_privilege_even_with_the_read_only_default_overridden(
    ops_url: str,
) -> None:
    # `default_transaction_read_only` is a session default the role can switch off, so it must
    # not be what stops a write here: override it and require the PRIVILEGE check to refuse
    # (negative control P3, 2026-09-19: with the default left on, a granted INSERT was masked and
    # the test passed anyway).
    with psycopg.connect(
        ops_url, autocommit=True, options="-c default_transaction_read_only=off"
    ) as conn:
        assert conn.execute("SHOW default_transaction_read_only").fetchone() == ("off",)
        for statement in (
            "INSERT INTO public.firms (name, plan, status) VALUES ('x', 'free', 'active')",
            "UPDATE public.firms SET name = 'x'",
            "DELETE FROM public.firms",
            "CREATE TABLE public.ops_monitor_should_not_exist (id int)",
            "CREATE ROLE ops_monitor_evil",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(statement)


@_NEEDS_PG
def test_role_default_session_is_read_only(ops_url: str) -> None:
    with (
        psycopg.connect(ops_url, autocommit=True) as conn,
        pytest.raises(psycopg.errors.ReadOnlySqlTransaction),
    ):
        conn.execute("CREATE TEMP TABLE ops_monitor_scratch (id int)")


@_NEEDS_PG
def test_collect_works_as_the_real_role_and_sees_real_numbers(ops_url: str) -> None:
    with psycopg.connect(ops_url, autocommit=True, prepare_threshold=None) as conn:
        snap = db_check.collect(conn, _T)
    assert snap.max_connections >= 1
    assert snap.total_sessions >= 1  # at least this session
    assert snap.total_sessions <= snap.max_connections
    assert isinstance(snap.statements_available, bool)


@_NEEDS_PG
def test_main_runs_end_to_end_as_the_real_role(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], ops_url: str
) -> None:
    monkeypatch.setenv("OPS_MONITOR_DATABASE_URL", ops_url)
    code = db_check.main()
    out = capsys.readouterr()
    assert code in (0, 1)  # 1 is legitimate on vanilla Postgres: pg_stat_statements isn't loaded
    assert "ops db-check: connections" in out.out
    password = make_url(ops_url).password
    assert password is not None
    assert password not in out.out + out.err
