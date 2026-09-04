"""notifications table

Run via MIGRATIONS_DATABASE_URL, same as prior migrations (DEPLOYMENT.md §2).

Revision ID: c72e9a1f4b83
Revises: f1c8a4d3b6e9
Create Date: 2026-09-04 13:40:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "c72e9a1f4b83"
down_revision: str | Sequence[str] | None = "f1c8a4d3b6e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # DATA_MODEL.md §2 `notifications` — recipient_id is always a single profile (schema-level
    # "never broadcast" guarantee), `type` is the 8-value CHECK per §5's enumeration table.
    op.execute("""
        CREATE TABLE notifications (
            id uuid NOT NULL DEFAULT gen_random_uuid(),
            firm_id uuid NOT NULL REFERENCES firms (id),
            recipient_id uuid NOT NULL,
            type text NOT NULL CHECK (type IN (
                'task_submitted', 'task_overdue', 'task_deadline_1_day', 'issue_raised',
                'task_assigned', 'task_reassigned', 'task_deadline_approaching', 'task_overdue_own'
            )),
            task_id uuid,
            issue_id uuid,
            is_read boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (firm_id, id),
            FOREIGN KEY (firm_id, recipient_id) REFERENCES profiles (firm_id, id),
            FOREIGN KEY (firm_id, task_id) REFERENCES tasks (firm_id, id),
            FOREIGN KEY (firm_id, issue_id) REFERENCES issues (firm_id, id)
        )
    """)
    # DATA_MODEL.md §2 — exactly the query the polling endpoint runs.
    op.execute(
        "CREATE INDEX ix_notifications_firm_recipient_read_created "
        "ON notifications (firm_id, recipient_id, is_read, created_at)"
    )
    op.execute("ALTER TABLE notifications ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE notifications FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON notifications
            USING (firm_id = current_setting('app.current_tenant', true)::uuid)
            WITH CHECK (firm_id = current_setting('app.current_tenant', true)::uuid)
    """)
    # UPDATE needed for PATCH /notifications/{id}/read; no DELETE — read notifications are kept,
    # not purged, matching every other resource in this schema.
    op.execute("GRANT SELECT, INSERT, UPDATE ON notifications TO fastapi_app")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS notifications")
