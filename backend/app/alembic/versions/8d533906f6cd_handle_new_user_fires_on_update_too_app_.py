"""handle_new_user fires on update too, app_metadata lands after insert

Real bug in c0f23284b2fd, caught by CI's e2e job (`test_admin_provisioned_user_gets_a_working_
real_token`) the same day: that migration made `handle_new_user()` read `firm_id`/`role` from
`raw_app_meta_data`, assuming it would be populated by the time the `AFTER INSERT ON auth.users`
trigger fires for an Admin-API-created user. Empirically false — GoTrue applies `app_metadata`
via a follow-up UPDATE *after* the initial insert, not as part of it (confirmed against Supabase's
own community troubleshooting material: "App metadata is updated after creating a user row in the
database, so you can't listen to the user insert call to update app metadata"). `raw_user_meta_data`
(what the old, less-safe version read) doesn't have this race — only `app_metadata` does, which is
exactly why this only broke once c0f23284b2fd switched the read. Every real admin-provisioned user
was failing outright: `profiles.firm_id` is NOT NULL (and part of the composite PK), so inserting
with a NULL firm_id at INSERT time raised a constraint violation, which GoTrue surfaces generically
as "Database error creating new user" — matches the observed CI failure exactly.

Fix: only provision the profile once `raw_app_meta_data->>'firm_id'` is actually present, and fire
the trigger on UPDATE as well as INSERT so it runs again once GoTrue's follow-up update lands that
data. `ON CONFLICT ... DO NOTHING` makes this safe to fire more than once for the same user (e.g. a
later unrelated metadata update) without erroring or re-provisioning.

Revision ID: 8d533906f6cd
Revises: c0f23284b2fd
Create Date: 2026-09-15 00:27:48.518930

"""

from collections.abc import Sequence

from alembic import op

revision: str = "8d533906f6cd"
down_revision: str | Sequence[str] | None = "c0f23284b2fd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION public.handle_new_user()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER SET search_path = ''
        AS $$
        BEGIN
            IF (new.raw_app_meta_data ->> 'firm_id') IS NOT NULL THEN
                INSERT INTO public.profiles
                    (id, firm_id, role, full_name, email, must_change_password, created_at)
                VALUES (
                    new.id,
                    (new.raw_app_meta_data ->> 'firm_id')::uuid,
                    new.raw_app_meta_data ->> 'role',
                    new.raw_user_meta_data ->> 'full_name',
                    new.email,
                    true,
                    now()
                )
                ON CONFLICT (id, firm_id) DO NOTHING;
            END IF;
            RETURN new;
        END;
        $$
    """)
    op.execute("DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users")
    op.execute("""
        CREATE TRIGGER on_auth_user_created
            AFTER INSERT OR UPDATE ON auth.users
            FOR EACH ROW EXECUTE FUNCTION public.handle_new_user()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users")
    op.execute("""
        CREATE TRIGGER on_auth_user_created
            AFTER INSERT ON auth.users
            FOR EACH ROW EXECUTE FUNCTION public.handle_new_user()
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION public.handle_new_user()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER SET search_path = ''
        AS $$
        BEGIN
            INSERT INTO public.profiles
                (id, firm_id, role, full_name, email, must_change_password, created_at)
            VALUES (
                new.id,
                (new.raw_app_meta_data ->> 'firm_id')::uuid,
                new.raw_app_meta_data ->> 'role',
                new.raw_user_meta_data ->> 'full_name',
                new.email,
                true,
                now()
            );
            RETURN new;
        END;
        $$
    """)
