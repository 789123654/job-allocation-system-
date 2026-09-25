"""Scheduled, read-only database health check: the leading indicators that precede an outage.

The k6 PATCH run (2026-09-18) went from healthy to `QueuePool limit ... reached` with nothing
warning beforehand. This looks at the database side of that picture — connection headroom, stuck or
slow work, lock waits, vacuum lag, table growth — and exits non-zero on ANY finding so a scheduled
GitHub Actions run turns it into a failure notification (no extra alerting service). Thresholds are
starting points for a pilot-scale database, to be tuned against real baselines, not measured
capacity limits.

What it can and cannot see (docs/OBSERVABILITY.md):
- It connects as `ops_monitor` (migration 2026-09-19): a LOGIN role with `pg_monitor`, no table
  privileges, no BYPASSRLS, read-only by role setting. It reads ONLY `pg_*` statistics views — a
  test enforces that no query here can name a tenant table — and prints aggregates and query IDs,
  never SQL text, tenant ids or row data.
- Fails closed: unreachable database, bad config, or a failed query is a FAILURE, not a pass.
- The DB URL comes from OPS_MONITOR_DATABASE_URL (an environment-scoped GitHub secret), never a
  CLI argument, so it can't appear in a process listing (Secrets_Management_Cheat_Sheet.md).
"""

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final, LiteralString

import psycopg
from pydantic import PostgresDsn, TypeAdapter, ValidationError

from app.core.dsn import require_tls_for_remote_hosts

_EXIT_OK, _EXIT_FINDINGS, _EXIT_CONFIG = 0, 1, 2
_CONNECT_TIMEOUT_SECONDS = 10
_ENV_VAR = "OPS_MONITOR_DATABASE_URL"

# Estimated live rows per table (pg_stat_user_tables.n_live_tup) above which growth needs a look.
# Placeholders sized for a 2,000-firm target, not measured — tune once real volumes exist.
_DEFAULT_TABLE_ROW_LIMITS: Mapping[str, int] = {
    "notifications": 1_000_000,
    "idempotency_keys": 1_000_000,
    "audit_log": 5_000_000,
    "access_denials": 1_000_000,
    "tasks": 5_000_000,
}


@dataclass(frozen=True)
class Thresholds:
    connections_ratio: float = 0.70
    idle_in_tx_seconds: int = 60
    long_running_seconds: int = 30
    blocked_seconds: int = 10
    slow_statement_ms: float = 500.0
    slow_statement_min_calls: int = 50
    dead_tuple_ratio: float = 0.20
    dead_tuple_min: int = 10_000
    table_row_limits: Mapping[str, int] = field(default_factory=lambda: _DEFAULT_TABLE_ROW_LIMITS)


@dataclass(frozen=True)
class SlowStatement:
    queryid: str
    mean_ms: float
    calls: int


@dataclass(frozen=True)
class Snapshot:
    max_connections: int
    total_sessions: int
    idle_in_tx: int
    long_running: int
    blocked: int
    slow_statements: list[SlowStatement]
    statements_available: bool
    dead_tables: list[tuple[str, int, int]]  # (table, dead, live)
    table_rows: dict[str, int]


@dataclass(frozen=True)
class Finding:
    check: str
    detail: str


# Every relation these queries read. tests/ops/test_db_check.py asserts that nothing else is ever
# named, so this tool can never be edited into reading a tenant table (multi-tenant safety).
_MAX_CONNECTIONS: Final = "SELECT current_setting('max_connections')::int"
_TOTAL_SESSIONS: Final = "SELECT count(*) FROM pg_stat_activity"
_IDLE_IN_TX: Final = (
    "SELECT count(*) FROM pg_stat_activity WHERE state = 'idle in transaction' "
    "AND pid <> pg_backend_pid() AND now() - state_change > make_interval(secs => %s)"
)
_LONG_RUNNING: Final = (
    "SELECT count(*) FROM pg_stat_activity WHERE state = 'active' "
    "AND backend_type = 'client backend' AND pid <> pg_backend_pid() "
    "AND now() - query_start > make_interval(secs => %s)"
)
_BLOCKED: Final = (
    "SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock' "
    "AND now() - state_change > make_interval(secs => %s)"
)
_SLOW_STATEMENTS: Final = (
    "SELECT queryid::text, mean_exec_time, calls FROM pg_stat_statements "
    "WHERE calls >= %s AND mean_exec_time > %s ORDER BY mean_exec_time DESC LIMIT 3"
)
_DEAD_TUPLES: Final = (
    "SELECT relname, n_dead_tup, n_live_tup FROM pg_stat_user_tables "
    "WHERE n_dead_tup > %s AND n_dead_tup::float8 / GREATEST(n_live_tup, 1) > %s "
    "ORDER BY n_dead_tup DESC LIMIT 5"
)
_TABLE_ROWS: Final = "SELECT relname, n_live_tup FROM pg_stat_user_tables WHERE relname = ANY(%s)"
ALL_QUERIES = (
    _MAX_CONNECTIONS,
    _TOTAL_SESSIONS,
    _IDLE_IN_TX,
    _LONG_RUNNING,
    _BLOCKED,
    _SLOW_STATEMENTS,
    _DEAD_TUPLES,
    _TABLE_ROWS,
)


def _scalar(conn: "psycopg.Connection[Any]", sql: LiteralString, *params: object) -> int:
    row = conn.execute(sql, params).fetchone()
    return int(row[0]) if row is not None else 0


def _slow_statements(
    conn: "psycopg.Connection[Any]", t: Thresholds
) -> tuple[list[SlowStatement], bool]:
    try:
        rows = conn.execute(_SLOW_STATEMENTS, (t.slow_statement_min_calls, t.slow_statement_ms))
        found = [SlowStatement(str(q), float(m), int(c)) for q, m, c in rows.fetchall()]
    except psycopg.Error:
        # Extension missing or not readable: an observability GAP, reported as a finding rather
        # than silently skipped (autocommit is on, so the connection stays usable).
        return [], False
    return found, True


def collect(conn: "psycopg.Connection[Any]", thresholds: Thresholds) -> Snapshot:
    slow, available = _slow_statements(conn, thresholds)
    dead = conn.execute(_DEAD_TUPLES, (thresholds.dead_tuple_min, thresholds.dead_tuple_ratio))
    rows = conn.execute(_TABLE_ROWS, (list(thresholds.table_row_limits),))
    return Snapshot(
        max_connections=_scalar(conn, _MAX_CONNECTIONS),
        total_sessions=_scalar(conn, _TOTAL_SESSIONS),
        idle_in_tx=_scalar(conn, _IDLE_IN_TX, thresholds.idle_in_tx_seconds),
        long_running=_scalar(conn, _LONG_RUNNING, thresholds.long_running_seconds),
        blocked=_scalar(conn, _BLOCKED, thresholds.blocked_seconds),
        slow_statements=slow,
        statements_available=available,
        dead_tables=[(str(n), int(d), int(lv)) for n, d, lv in dead.fetchall()],
        table_rows={str(n): int(v) for n, v in rows.fetchall()},
    )


def _connection_finding(snap: Snapshot, t: Thresholds) -> list[Finding]:
    if (
        snap.max_connections <= 0
        or snap.total_sessions / snap.max_connections < t.connections_ratio
    ):
        return []
    detail = (
        f"{snap.total_sessions} of {snap.max_connections} sessions in use "
        f"(warn at {t.connections_ratio:.0%})"
    )
    return [Finding("connections", detail)]


def evaluate(snap: Snapshot, t: Thresholds) -> list[Finding]:
    """Pure function of a snapshot: every rule is unit-tested at its boundary."""
    findings = _connection_finding(snap, t)
    counted = (
        ("idle_in_transaction", snap.idle_in_tx, f"idle in transaction > {t.idle_in_tx_seconds}s"),
        ("long_running_queries", snap.long_running, f"active > {t.long_running_seconds}s"),
        ("lock_waits", snap.blocked, f"waiting on a lock > {t.blocked_seconds}s"),
    )
    findings += [Finding(check, f"{n} session(s) {what}") for check, n, what in counted if n > 0]
    if not snap.statements_available:
        findings.append(Finding("pg_stat_statements", "unavailable: no query-level visibility"))
    findings += [
        Finding("slow_statement", f"queryid {s.queryid}: mean {s.mean_ms:.0f}ms, {s.calls} calls")
        for s in snap.slow_statements
    ]
    findings += [
        Finding("vacuum_lag", f"{name}: {dead} dead vs {live} live tuples")
        for name, dead, live in snap.dead_tables
    ]
    findings += [
        Finding("table_growth", f"{name}: ~{rows} rows (limit {t.table_row_limits[name]})")
        for name, rows in sorted(snap.table_rows.items())
        if name in t.table_row_limits and rows >= t.table_row_limits[name]
    ]
    return findings


def _database_url() -> str:
    """The validated URL, or ValueError. Never echoes the URL: it contains a credential."""
    url = os.environ.get(_ENV_VAR, "")
    if not url:
        raise ValueError("not set")
    # The app's own URLs use the SQLAlchemy driver prefix; libpq/psycopg wants the plain scheme.
    plain = url.replace("postgresql+psycopg://", "postgresql://", 1)
    try:
        dsn = TypeAdapter(PostgresDsn).validate_python(plain)
    except ValidationError:
        raise ValueError("not a Postgres URL") from None
    require_tls_for_remote_hosts(dsn)  # ASVS 12.3: verify-full for anything off this machine
    return plain


def _write(stream: Any, text: str) -> None:
    stream.write(text + "\n")


def main() -> int:
    try:
        url = _database_url()
    except ValueError:
        _write(
            sys.stderr, f"ops db-check: {_ENV_VAR} is missing or invalid (docs/OBSERVABILITY.md)"
        )
        return _EXIT_CONFIG
    thresholds = Thresholds()
    try:
        # prepare_threshold=None: the shared pooler's transaction mode can't do prepared statements.
        with psycopg.connect(
            url, connect_timeout=_CONNECT_TIMEOUT_SECONDS, autocommit=True, prepare_threshold=None
        ) as conn:
            snapshot = collect(conn, thresholds)
    except psycopg.Error as exc:
        # Class name only: a driver message can embed the host or credentials.
        _write(sys.stderr, f"ops db-check: could not query the database ({type(exc).__name__})")
        return _EXIT_FINDINGS
    findings = evaluate(snapshot, thresholds)
    _write(
        sys.stdout,
        f"ops db-check: connections {snapshot.total_sessions}/{snapshot.max_connections}, "
        f"idle-in-tx {snapshot.idle_in_tx}, long-running {snapshot.long_running}, "
        f"lock-waits {snapshot.blocked}, slow-statements {len(snapshot.slow_statements)}, "
        f"vacuum-lag tables {len(snapshot.dead_tables)}",
    )
    for finding in findings:
        _write(sys.stdout, f"FINDING {finding.check}: {finding.detail}")
    _write(sys.stdout, "ops db-check: " + ("FAILED" if findings else "OK"))
    return _EXIT_FINDINGS if findings else _EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
