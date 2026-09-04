"""tasks and idempotency_keys tables

Run via MIGRATIONS_DATABASE_URL, same as prior migrations (DEPLOYMENT.md §2).

Revision ID: dd9b07e031bf
Revises: 9104a25b4614
Create Date: 2026-09-04 15:02:11.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "dd9b07e031bf"
down_revision: str | Sequence[str] | None = "9104a25b4614"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # DATA_MODEL.md `tasks` §2 — composite PK/FK convention throughout. Two composite self/cross
    # FKs (parent_task_id, job_type_id) declared as ADD CONSTRAINT after CREATE TABLE since
    # job_type_id -> job_types(firm_id, id) and parent_task_id -> tasks(firm_id, id) both need the
    # table (or job_types) to already exist — job_types already does (previous migration).
    op.execute("""
        CREATE TABLE tasks (
            id uuid NOT NULL DEFAULT gen_random_uuid(),
            firm_id uuid NOT NULL REFERENCES firms (id),
            job_type_id uuid,
            task_type text NOT NULL DEFAULT 'standard' CHECK (task_type IN ('standard', 'billing')),
            parent_task_id uuid,
            title text NOT NULL,
            description text,
            assigned_to uuid,
            deadline timestamptz,
            status text NOT NULL DEFAULT 'created'
                CHECK (status IN
                    ('created', 'assigned', 'in_progress', 'submitted', 'completed', 'billed')),
            created_by uuid NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            last_reassignment_notes text,
            last_reassignment_remaining_work text,
            last_reassignment_source text CHECK (last_reassignment_source IN ('review', 'issue')),
            last_reassignment_at timestamptz,
            billing_amount numeric,
            billing_recipient text,
            PRIMARY KEY (firm_id, id),
            FOREIGN KEY (firm_id, job_type_id) REFERENCES job_types (firm_id, id),
            FOREIGN KEY (firm_id, parent_task_id) REFERENCES tasks (firm_id, id),
            FOREIGN KEY (firm_id, assigned_to) REFERENCES profiles (firm_id, id),
            FOREIGN KEY (firm_id, created_by) REFERENCES profiles (firm_id, id)
        )
    """)
    op.execute("CREATE INDEX ix_tasks_firm_assigned_status ON tasks (firm_id, assigned_to, status)")
    op.execute("CREATE INDEX ix_tasks_firm_status_deadline ON tasks (firm_id, status, deadline)")
    op.execute("CREATE INDEX ix_tasks_firm_type_status ON tasks (firm_id, task_type, status)")

    op.execute("ALTER TABLE tasks ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tasks FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON tasks
            USING (firm_id = current_setting('app.current_tenant', true)::uuid)
            WITH CHECK (firm_id = current_setting('app.current_tenant', true)::uuid)
    """)
    # No DELETE — tasks are never hard-deleted, matching every other resource in this schema.
    op.execute("GRANT SELECT, INSERT, UPDATE ON tasks TO fastapi_app")

    # rest-api-guidelines Rule 230 (checked directly 2026-09-04, not assumed) — the Idempotency-Key
    # header pattern for POST /tasks, /tasks/{id}/submit, /tasks/{id}/mark-billed (API_SPEC.md,
    # "the strongest of the three patterns" for task creation specifically). The unique constraint
    # is what turns a genuine race between two identical concurrent retries into a caught conflict
    # instead of two rows — the "hard transaction semantics" the rule itself calls out as the hard
    # part, made cheap here because this is a single Postgres instance, not a distributed system.
    op.execute("""
        CREATE TABLE idempotency_keys (
            firm_id uuid NOT NULL REFERENCES firms (id),
            actor_id uuid NOT NULL,
            idempotency_key text NOT NULL,
            endpoint text NOT NULL,
            request_hash text NOT NULL,
            response_status integer NOT NULL,
            response_body jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (firm_id, actor_id, idempotency_key, endpoint),
            FOREIGN KEY (firm_id, actor_id) REFERENCES profiles (firm_id, id)
        )
    """)
    op.execute("ALTER TABLE idempotency_keys ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE idempotency_keys FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON idempotency_keys
            USING (firm_id = current_setting('app.current_tenant', true)::uuid)
            WITH CHECK (firm_id = current_setting('app.current_tenant', true)::uuid)
    """)
    # Append-only from the app's perspective — a row is looked up and inserted, never modified.
    # ponytail: no cleanup job for rows past the 24h TTL yet (a lookup filters them out by
    # created_at regardless, so correctness doesn't depend on deletion) — add a scheduled DELETE
    # once row count at pilot scale actually justifies it, not speculatively now.
    op.execute("GRANT SELECT, INSERT ON idempotency_keys TO fastapi_app")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS idempotency_keys")
    op.execute("DROP TABLE IF EXISTS tasks")
