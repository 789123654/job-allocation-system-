"""wrap current_setting in RLS policies for initplan caching

Supabase performance advisor, checked live 2026-09-19 (docs/OBSERVABILITY.md §9 item 10):
`auth_rls_initplan` WARN on all 10 `tenant_isolation` policies — `current_setting()` is
re-evaluated once per row instead of once per statement. Documented fix, verified against
supabase-official/database/row-level-security.md ("Call functions with select"): wrapping the
function call in `(select ...)` makes the Postgres planner run it as an initPlan and cache the
result for the statement, instead of calling it per row.

Safe here specifically because `app.current_tenant` is set once per transaction via `SET LOCAL`
(ARCHITECTURE.md §4 step 6) and never varies by row within a statement — exactly the condition the
Supabase doc's own caution names ("only if the results ... do not change based on the row data").

Behavior is unchanged, only the query plan — proven, not assumed, by running
tests/crud/test_rls_isolation.py (cross-tenant read/update must still return zero rows) against a
real Postgres both before and after this migration.

Revision ID: 98a451df3e44
Revises: 66bc34819e6a
Create Date: 2026-09-25 23:56:11.740534

"""

from collections.abc import Sequence

from alembic import op

revision: str = "98a451df3e44"
down_revision: str | Sequence[str] | None = "66bc34819e6a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, column) for every tenant_isolation policy that exists today (docs/OBSERVABILITY.md §9
# item 10 counted exactly 10 live policies) — firms is keyed by its own id, everything else by
# firm_id.
_POLICIES = [
    ("firms", "id"),
    ("profiles", "firm_id"),
    ("job_types", "firm_id"),
    ("tasks", "firm_id"),
    ("idempotency_keys", "firm_id"),
    ("notifications", "firm_id"),
    ("access_denials", "firm_id"),
    ("audit_log", "firm_id"),
    ("task_reviews", "firm_id"),
    ("issues", "firm_id"),
]


def upgrade() -> None:
    for table, column in _POLICIES:
        op.execute(f"""
            ALTER POLICY tenant_isolation ON {table}
                USING ({column} = (select current_setting('app.current_tenant', true))::uuid)
                WITH CHECK ({column} = (select current_setting('app.current_tenant', true))::uuid)
        """)


def downgrade() -> None:
    for table, column in _POLICIES:
        op.execute(f"""
            ALTER POLICY tenant_isolation ON {table}
                USING ({column} = current_setting('app.current_tenant', true)::uuid)
                WITH CHECK ({column} = current_setting('app.current_tenant', true)::uuid)
        """)
