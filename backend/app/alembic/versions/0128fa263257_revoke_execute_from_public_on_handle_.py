"""revoke execute from public on handle_new_user and rls_auto_enable

Follow-up to 82764b1d04cb: that migration revoked EXECUTE from `anon`/`authenticated` by name, but
querying the live project's actual ACL (`pg_proc.proacl`, via the Supabase MCP `execute_sql` tool)
showed `{=X/postgres,postgres=X/postgres,service_role=X/postgres}` — the bare `=X` entry is the
implicit `PUBLIC` pseudo-role, which is what Postgres grants EXECUTE to by default on function
creation. `anon`/`authenticated` were never granted EXECUTE directly; they inherit it through PUBLIC
like every role does, so the prior migration's named-role revoke was a no-op (confirmed: the
Supabase security advisor still flagged both functions afterward). Revoking from PUBLIC is the
actual fix. Same reasoning as before on why this is safe: both functions are only ever fired via
their trigger/event-trigger mechanism, which is not gated by the EXECUTE privilege check that
governs direct/RPC calls.

Revision ID: 0128fa263257
Revises: 82764b1d04cb
Create Date: 2026-09-16 01:09:06.901527

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0128fa263257"
down_revision: str | Sequence[str] | None = "82764b1d04cb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("REVOKE EXECUTE ON FUNCTION public.handle_new_user() FROM PUBLIC")
    # Same guard as 82764b1d04cb, same reason: rls_auto_enable() only exists on the real Supabase
    # project, never created by any migration in this repo — a bare REVOKE fails UndefinedFunction
    # on any fresh bootstrap (ci.yml/loadtest.yml). No-op where it doesn't exist, real revoke where
    # it does.
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_proc WHERE proname = 'rls_auto_enable'
                AND pronamespace = 'public'::regnamespace
            ) THEN
                REVOKE EXECUTE ON FUNCTION public.rls_auto_enable() FROM PUBLIC;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("GRANT EXECUTE ON FUNCTION public.handle_new_user() TO PUBLIC")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_proc WHERE proname = 'rls_auto_enable'
                AND pronamespace = 'public'::regnamespace
            ) THEN
                GRANT EXECUTE ON FUNCTION public.rls_auto_enable() TO PUBLIC;
            END IF;
        END $$;
    """)
