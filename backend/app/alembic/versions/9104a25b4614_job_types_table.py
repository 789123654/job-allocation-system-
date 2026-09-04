"""job_types table

Run via MIGRATIONS_DATABASE_URL, same as prior migrations (DEPLOYMENT.md §2).

Revision ID: 9104a25b4614
Revises: 4cf3e294633d
Create Date: 2026-09-04 14:17:54.875155

"""

from collections.abc import Sequence

from alembic import op

revision: str = "9104a25b4614"
down_revision: str | Sequence[str] | None = "4cf3e294633d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # DATA_MODEL.md `job_types` — composite PK/FK convention (DATA_MODEL.md §1), UNIQUE(firm_id,
    # name) is the "Secondary key" idempotency pattern API_SPEC.md names for POST /job-types (a
    # duplicate create hits this constraint, caught and turned into a 409 — same shape as
    # Employees' email-uniqueness dedup, no new Idempotency-Key infra needed for this resource).
    op.execute("""
        CREATE TABLE job_types (
            id uuid NOT NULL DEFAULT gen_random_uuid(),
            firm_id uuid NOT NULL REFERENCES firms (id),
            name text NOT NULL,
            is_active boolean NOT NULL DEFAULT true,
            created_by uuid NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (firm_id, id),
            FOREIGN KEY (firm_id, created_by) REFERENCES profiles (firm_id, id),
            UNIQUE (firm_id, name)
        )
    """)

    op.execute("ALTER TABLE job_types ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE job_types FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON job_types
            USING (firm_id = current_setting('app.current_tenant', true)::uuid)
            WITH CHECK (firm_id = current_setting('app.current_tenant', true)::uuid)
    """)

    # UPDATE is real here (unlike audit_log) — PATCH /job-types/{id} flips is_active. Still no
    # DELETE: soft-delete only, existing tasks may reference a retired template.
    op.execute("GRANT SELECT, INSERT, UPDATE ON job_types TO fastapi_app")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS job_types")
