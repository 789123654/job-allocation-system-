"""audit_log table

Run via MIGRATIONS_DATABASE_URL, same as the first migration (DEPLOYMENT.md §2).

Revision ID: 4cf3e294633d
Revises: cb67cdb7538a
Create Date: 2026-09-03 18:10:48.182938

"""

from collections.abc import Sequence

from alembic import op

revision: str = "4cf3e294633d"
down_revision: str | Sequence[str] | None = "cb67cdb7538a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # DATA_MODEL.md `audit_log` — append-only, no updated_at, no soft-delete. Composite FKs to
    # profiles (not plain FKs) per the composite-FK convention (DATA_MODEL.md §1).
    op.execute("""
        CREATE TABLE audit_log (
            id uuid NOT NULL DEFAULT gen_random_uuid(),
            firm_id uuid NOT NULL REFERENCES firms (id),
            actor_id uuid NOT NULL,
            action text NOT NULL
                CHECK (action IN ('employee_created', 'employee_deactivated',
                                   'employee_reactivated', 'password_reset')),
            target_id uuid,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (firm_id, id),
            FOREIGN KEY (firm_id, actor_id) REFERENCES profiles (firm_id, id),
            FOREIGN KEY (firm_id, target_id) REFERENCES profiles (firm_id, id)
        )
    """)
    op.execute("CREATE INDEX ix_audit_log_firm_created ON audit_log (firm_id, created_at)")

    op.execute("ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_log FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON audit_log
            USING (firm_id = current_setting('app.current_tenant', true)::uuid)
            WITH CHECK (firm_id = current_setting('app.current_tenant', true)::uuid)
    """)

    # Rows are never modified or removed once written — no UPDATE/DELETE grant (DATA_MODEL.md).
    op.execute("GRANT SELECT, INSERT ON audit_log TO fastapi_app")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit_log")
