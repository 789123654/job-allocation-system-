"""add ops_monitor read-only monitoring role

Run via MIGRATIONS_DATABASE_URL, same as the fastapi_app role migration (DEPLOYMENT.md §2).

Observability Phase 1 item 5: backend/ops/db_check.py (scheduled) needs to read connection, lock,
slow-statement and vacuum statistics. It must NOT do that as fastapi_app (that role's one job is
tenant data under RLS) nor as `postgres` (BYPASSRLS). A third role with `pg_monitor` and nothing
else:
- no table privileges anywhere (a fresh role gets none; verified by tests/ops/test_db_check.py's
  real-Postgres test, which connects as this role and is refused a SELECT on every tenant table);
- NOBYPASSRLS, NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOREPLICATION;
- CONNECTION LIMIT 2, so a runaway monitor can't consume the scarce max_connections (60 live);
- read-only / bounded by role-level settings. `default_transaction_read_only` is a default the
  session can override, so it is defense-in-depth, not the boundary — the boundary is the absence
  of any write or table privilege.

`pg_monitor` (not `pg_read_all_stats` alone): the Supabase `postgres` role holds ADMIN on
pg_monitor but not on its member roles, so only pg_monitor can be granted here (checked against
pg_auth_members on the live project, 2026-09-19). pg_monitor also lets the role SEE other
sessions' query text in pg_stat_activity; db_check.py never selects that column and a test pins
the queries it runs.

No password is set here and none is committed (same as fastapi_app): set it out-of-band with
`ALTER ROLE ops_monitor WITH PASSWORD ...` from a secrets-managed value, then store the URL as the
`OPS_MONITOR_DATABASE_URL` GitHub environment secret (docs/OBSERVABILITY.md). Until then the role
cannot log in (password authentication has nothing to match).

Revision ID: 66bc34819e6a
Revises: 178722372dba
Create Date: 2026-09-19 02:40:11.453458

"""

from collections.abc import Sequence

from alembic import op

revision: str = "66bc34819e6a"
down_revision: str | Sequence[str] | None = "178722372dba"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE ROLE ops_monitor WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
        "NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 2"
    )
    op.execute("GRANT pg_monitor TO ops_monitor")
    op.execute("ALTER ROLE ops_monitor SET default_transaction_read_only = on")
    op.execute("ALTER ROLE ops_monitor SET statement_timeout = '10s'")
    op.execute("ALTER ROLE ops_monitor SET idle_in_transaction_session_timeout = '30s'")
    op.execute("ALTER ROLE ops_monitor SET lock_timeout = '2s'")


def downgrade() -> None:
    # The role owns nothing and holds no table privileges, so a plain DROP suffices; its role-level
    # settings and pg_monitor membership go with it.
    op.execute("DROP ROLE IF EXISTS ops_monitor")
