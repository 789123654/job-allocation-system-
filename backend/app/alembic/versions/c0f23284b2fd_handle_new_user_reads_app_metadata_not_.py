"""handle_new_user reads app_metadata not user_metadata

Code review finding #11 (2026-09-14): `handle_new_user()` (cb67cdb7538a) sourced `firm_id`/`role`
from `raw_user_meta_data` — the field a user can set on themselves via Supabase's public
`signUp()`/`updateUser()` (confirmed directly against the installed `supabase_auth` SDK's
`AdminUserAttributes` type and Supabase's own JS reference docs, not assumed: `auth-updateuser`'s
client-side method has no `app_metadata` parameter at all, only `auth-admin-updateUserById`'s
server-only Admin API does). `supabase-official/auth/users.md`'s own `user_metadata` row already
warns: "Do not use it in security sensitive context ... as this value is editable by the user
without any checks." `Mass_Assignment_Cheat_Sheet.md`'s core lesson (bind only an explicit
allowlist, never trust the whole payload) applies directly — `firm_id`/`role` are exactly the
"isAdmin"-shaped privileged fields that cheat sheet warns never to source from client-controlled
input. TCASVS 1.1.5/1.1.6 (trust boundaries the threat model must document, protection mechanisms
at each crossing) names this exact client-to-backend boundary.

Today this trigger is only ever reached via the trusted path (crud.create_employee -> Admin API,
backend-controlled), and `supabase/config.toml` disables public signup — but that's a project
config toggle, not a structural guarantee, and DEPLOYMENT.md's own go-live runbook never actually
required verifying it stays off in production (the doc-drift half of this same finding, fixed
separately in DEPLOYMENT.md). This migration is the structural fix: even if signup were ever
enabled, `raw_app_meta_data` cannot be set by an unprivileged caller, so a self-registered user can
never assign themselves a `firm_id`/`role` this way again. `full_name` stays sourced from
`raw_user_meta_data` — it's display-only, not a privilege/tenant field, so the client-editable
warning doesn't apply to it the way it does to firm_id/role.

Revision ID: c0f23284b2fd
Revises: 824d532c93a2
Create Date: 2026-09-14 18:42:01.688269

"""

from collections.abc import Sequence

from alembic import op

revision: str = "c0f23284b2fd"
down_revision: str | Sequence[str] | None = "824d532c93a2"
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


def downgrade() -> None:
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
