"""revoke public execute on handle_new_user and rls_auto_enable

Supabase security advisor (2026-09-16), checked via the Supabase MCP `get_advisors` tool against
the real project: both functions are `SECURITY DEFINER` and, by Postgres's default EXECUTE-to-PUBLIC
grant on function creation, callable directly by `anon`/`authenticated` via PostgREST's
`/rest/v1/rpc/<fn>` — even though both exist only to be fired as a trigger (`handle_new_user`,
`RETURNS trigger`) / event trigger (`rls_auto_enable`, `RETURNS event_trigger`). Postgres itself
already refuses to execute either outside its real trigger context ("trigger functions can only be
called as triggers"), so there is no exploit path today — but that safety is incidental to the
return type, not designed in, and revoking EXECUTE removes the reliance on it. Revoking EXECUTE
does not affect the trigger firing itself: trigger invocation is not gated by the EXECUTE privilege
check that governs direct/RPC calls.

Revision ID: 82764b1d04cb
Revises: 8d533906f6cd
Create Date: 2026-09-16 01:06:38.022082

"""

from collections.abc import Sequence

from alembic import op

revision: str = "82764b1d04cb"
down_revision: str | Sequence[str] | None = "8d533906f6cd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("REVOKE EXECUTE ON FUNCTION public.handle_new_user() FROM anon, authenticated")
    op.execute("REVOKE EXECUTE ON FUNCTION public.rls_auto_enable() FROM anon, authenticated")


def downgrade() -> None:
    op.execute("GRANT EXECUTE ON FUNCTION public.handle_new_user() TO anon, authenticated")
    op.execute("GRANT EXECUTE ON FUNCTION public.rls_auto_enable() TO anon, authenticated")
