"""access_denials table

Run via MIGRATIONS_DATABASE_URL, same as the first migration (DEPLOYMENT.md §2).

Revision ID: dc5f39cce3f9
Revises: c72e9a1f4b83
Create Date: 2026-09-05 02:32:52.011512

"""

from collections.abc import Sequence

from alembic import op

revision: str = "dc5f39cce3f9"
down_revision: str | Sequence[str] | None = "c72e9a1f4b83"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # DATA_MODEL.md `access_denials` — append-only, no updated_at, no soft-delete. resource_id is
    # deliberately NOT an FK (the whole point is it may reference something the actor can't see).
    op.execute("""
        CREATE TABLE access_denials (
            id uuid NOT NULL DEFAULT gen_random_uuid(),
            firm_id uuid NOT NULL REFERENCES firms (id),
            actor_id uuid NOT NULL,
            resource_type text
                CHECK (resource_type IN ('task', 'notification')),
            resource_id uuid,
            reason text NOT NULL
                CHECK (reason IN ('wrong_role', 'not_assignee', 'wrong_owner')),
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (firm_id, id),
            FOREIGN KEY (firm_id, actor_id) REFERENCES profiles (firm_id, id)
        )
    """)
    op.execute(
        "CREATE INDEX ix_access_denials_firm_created ON access_denials (firm_id, created_at)"
    )

    op.execute("ALTER TABLE access_denials ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE access_denials FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON access_denials
            USING (firm_id = current_setting('app.current_tenant', true)::uuid)
            WITH CHECK (firm_id = current_setting('app.current_tenant', true)::uuid)
    """)

    # Rows are never modified or removed once written — no UPDATE/DELETE grant (DATA_MODEL.md).
    op.execute("GRANT SELECT, INSERT ON access_denials TO fastapi_app")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS access_denials")
