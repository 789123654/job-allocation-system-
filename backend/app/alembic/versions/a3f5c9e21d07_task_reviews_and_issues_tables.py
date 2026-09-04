"""task_reviews and issues tables

Run via MIGRATIONS_DATABASE_URL, same as prior migrations (DEPLOYMENT.md §2).

Revision ID: a3f5c9e21d07
Revises: dd9b07e031bf
Create Date: 2026-09-04 16:10:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "a3f5c9e21d07"
down_revision: str | Sequence[str] | None = "dd9b07e031bf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # DATA_MODEL.md `task_reviews` — pure audit trail of the 3-way review outcome, kept separate
    # from tasks.status so history survives a task cycling back to in_progress more than once.
    op.execute("""
        CREATE TABLE task_reviews (
            id uuid NOT NULL DEFAULT gen_random_uuid(),
            firm_id uuid NOT NULL REFERENCES firms (id),
            task_id uuid NOT NULL,
            reviewed_by uuid NOT NULL,
            outcome text NOT NULL CHECK (outcome IN ('approved', 'reassigned', 'billing')),
            notes text,
            remaining_work_description text,
            resulting_billing_task_id uuid,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (firm_id, id),
            FOREIGN KEY (firm_id, task_id) REFERENCES tasks (firm_id, id),
            FOREIGN KEY (firm_id, reviewed_by) REFERENCES profiles (firm_id, id),
            FOREIGN KEY (firm_id, resulting_billing_task_id) REFERENCES tasks (firm_id, id)
        )
    """)
    op.execute("CREATE INDEX ix_task_reviews_firm_task ON task_reviews (firm_id, task_id)")
    op.execute("ALTER TABLE task_reviews ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE task_reviews FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON task_reviews
            USING (firm_id = current_setting('app.current_tenant', true)::uuid)
            WITH CHECK (firm_id = current_setting('app.current_tenant', true)::uuid)
    """)
    # Append-only — a review outcome is never edited or deleted once recorded.
    op.execute("GRANT SELECT, INSERT ON task_reviews TO fastapi_app")

    # DATA_MODEL.md `issues` — raised open, resolved once (resolution fields fill in via UPDATE).
    op.execute("""
        CREATE TABLE issues (
            id uuid NOT NULL DEFAULT gen_random_uuid(),
            firm_id uuid NOT NULL REFERENCES firms (id),
            task_id uuid NOT NULL,
            raised_by uuid NOT NULL,
            description text NOT NULL,
            status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved')),
            resolution_type text
                CHECK (resolution_type IN ('clarified', 'deadline_adjusted', 'reassigned')),
            resolution_notes text,
            resolved_by uuid,
            resolved_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (firm_id, id),
            FOREIGN KEY (firm_id, task_id) REFERENCES tasks (firm_id, id),
            FOREIGN KEY (firm_id, raised_by) REFERENCES profiles (firm_id, id),
            FOREIGN KEY (firm_id, resolved_by) REFERENCES profiles (firm_id, id)
        )
    """)
    op.execute("CREATE INDEX ix_issues_firm_task_status ON issues (firm_id, task_id, status)")
    op.execute("ALTER TABLE issues ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE issues FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON issues
            USING (firm_id = current_setting('app.current_tenant', true)::uuid)
            WITH CHECK (firm_id = current_setting('app.current_tenant', true)::uuid)
    """)
    # UPDATE needed here (unlike task_reviews) — resolving fills in resolution_* columns in place.
    op.execute("GRANT SELECT, INSERT, UPDATE ON issues TO fastapi_app")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS issues")
    op.execute("DROP TABLE IF EXISTS task_reviews")
