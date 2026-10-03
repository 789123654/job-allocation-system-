"""task_edits: append-only history of owner edits to a task before the employee starts.

audit_log can't hold this: its action CHECK only allows employee/password actions, its target_id
FK points at profiles, and it has no payload for old/new values (DATA_MODEL.md audit_log section).

Revision ID: 7c1e9b4d2a60
Revises: 98a451df3e44
"""

from collections.abc import Sequence

from alembic import op

revision: str = "7c1e9b4d2a60"
down_revision: str | Sequence[str] | None = "98a451df3e44"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE task_edits (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            firm_id uuid NOT NULL REFERENCES firms (id),
            task_id uuid NOT NULL,
            edited_by uuid NOT NULL,
            changed_fields jsonb NOT NULL CHECK (jsonb_typeof(changed_fields) = 'object'),
            created_at timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (firm_id, task_id) REFERENCES tasks (firm_id, id),
            FOREIGN KEY (firm_id, edited_by) REFERENCES profiles (firm_id, id)
        )
    """)
    op.execute("CREATE INDEX ix_task_edits_firm_task ON task_edits (firm_id, task_id)")
    op.execute("ALTER TABLE task_edits ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE task_edits FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON task_edits
            USING (firm_id = (select current_setting('app.current_tenant', true))::uuid)
            WITH CHECK (firm_id = (select current_setting('app.current_tenant', true))::uuid)
    """)
    # No UPDATE or DELETE grant: history rows are never edited or removed (same as audit_log).
    op.execute("GRANT SELECT, INSERT ON task_edits TO fastapi_app")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS task_edits")
