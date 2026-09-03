"""firms and profiles, fastapi_app role, RLS, provisioning trigger

Run only via MIGRATIONS_DATABASE_URL (DEPLOYMENT.md §2) — CREATE ROLE and the trigger on auth.users
both need privileges fastapi_app itself must never have.

Revision ID: cb67cdb7538a
Revises:
Create Date: 2026-09-03 17:19:06.770623

"""

from collections.abc import Sequence

from alembic import op

revision: str = "cb67cdb7538a"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Least-privilege runtime role — plain CREATE ROLE carries no BYPASSRLS by default
    # (ARCHITECTURE.md §5). Password is set out-of-band immediately after (e.g.
    # `ALTER ROLE fastapi_app WITH PASSWORD ...` from a secrets-managed value), never committed.
    op.execute("CREATE ROLE fastapi_app WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS")

    op.execute("""
        CREATE TABLE firms (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            name text NOT NULL,
            plan text NOT NULL,
            status text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    # DATA_MODEL.md / ARCHITECTURE.md §5 finding: firms has no firm_id self-column, so it needs
    # its own self-referential policy, not the standard tenant_isolation pattern used elsewhere.
    op.execute("ALTER TABLE firms ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE firms FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON firms
            USING (id = current_setting('app.current_tenant', true)::uuid)
            WITH CHECK (id = current_setting('app.current_tenant', true)::uuid)
    """)

    op.execute("""
        CREATE TABLE profiles (
            id uuid NOT NULL,
            firm_id uuid NOT NULL REFERENCES firms (id),
            role text NOT NULL CHECK (role IN ('owner', 'employee')),
            full_name text NOT NULL,
            email text NOT NULL,
            is_active boolean NOT NULL DEFAULT true,
            must_change_password boolean NOT NULL DEFAULT true,
            last_reset_by uuid,
            last_reset_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (firm_id, id),
            FOREIGN KEY (firm_id, last_reset_by) REFERENCES profiles (firm_id, id)
        )
    """)
    op.execute("ALTER TABLE profiles ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE profiles FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON profiles
            USING (firm_id = current_setting('app.current_tenant', true)::uuid)
            WITH CHECK (firm_id = current_setting('app.current_tenant', true)::uuid)
    """)

    op.execute("GRANT USAGE ON SCHEMA public TO fastapi_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON firms, profiles TO fastapi_app")

    # ARCHITECTURE.md §4 provisioning / DATA_MODEL.md `profiles`: fires on admin.createUser(),
    # same transaction, reads firm_id/role out of raw_user_meta_data. SECURITY DEFINER + empty
    # search_path both load-bearing — Supabase's own managing-user-data.md pattern, not boilerplate.
    op.execute("""
        CREATE FUNCTION public.handle_new_user()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER SET search_path = ''
        AS $$
        BEGIN
            INSERT INTO public.profiles
                (id, firm_id, role, full_name, email, must_change_password, created_at)
            VALUES (
                new.id,
                (new.raw_user_meta_data ->> 'firm_id')::uuid,
                new.raw_user_meta_data ->> 'role',
                new.raw_user_meta_data ->> 'full_name',
                new.email,
                true,
                now()
            );
            RETURN new;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER on_auth_user_created
            AFTER INSERT ON auth.users
            FOR EACH ROW EXECUTE FUNCTION public.handle_new_user()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users")
    op.execute("DROP FUNCTION IF EXISTS public.handle_new_user()")
    op.execute("DROP TABLE IF EXISTS profiles")
    op.execute("DROP TABLE IF EXISTS firms")
    op.execute("DROP ROLE IF EXISTS fastapi_app")
