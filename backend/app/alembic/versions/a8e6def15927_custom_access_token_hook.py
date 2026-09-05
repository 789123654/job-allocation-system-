"""custom access token hook — injects firm_id/role/must_change_password into app_metadata

Run only via MIGRATIONS_DATABASE_URL (DEPLOYMENT.md §2) — granting to supabase_auth_admin needs
privileges fastapi_app itself must never have. After this migration runs, the hook must still be
enabled manually in the Supabase dashboard (Authentication > Hooks > Customize Access Token) —
Alembic creates the function, it does not register it as an active hook.

ARCHITECTURE.md §4 step 2 already described this hook injecting firm_id + role; it had never
actually been built as SQL anywhere in this repo (confirmed by grep before writing this). Adds
must_change_password alongside the two originally-described claims — found necessary while
building the frontend's session routing (Phase 4): the frontend cannot query `profiles` directly
(ARCHITECTURE.md's "frontend never talks to Postgres/PostgREST directly" rule) and no FastAPI
endpoint exposes this value, so client-side routing to the forced Set New Password screen had no
way to learn it otherwise.

Same staleness caveat already accepted for firm_id/role (ARCHITECTURE.md §4: token-lifetime-scoped,
not live) applies here too — acceptable specifically because this claim only drives client-side
*routing* (UX only), while the real enforcement stays server-side and live on every request
(backend/app/api/deps.py's require_password_set, unaffected by this migration). The frontend forces
a session refresh (`supabase.auth.refreshSession()`) immediately after Set New Password succeeds so
the UI updates without waiting for natural token expiry.

Revision ID: a8e6def15927
Revises: dc5f39cce3f9
Create Date: 2026-09-05 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "a8e6def15927"
down_revision: str | Sequence[str] | None = "dc5f39cce3f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SECURITY DEFINER + empty search_path: same load-bearing pattern as handle_new_user()
    # (cb67cdb7538a) — Supabase's own custom-access-token-hook.md examples for a hook reading a
    # profiles table (its "Add admin role" example) don't mark SECURITY DEFINER explicitly, but
    # supabase_auth_admin needs to read `profiles` regardless of the calling user's own RLS
    # context, and empty search_path defends the same schema-injection risk handle_new_user()
    # already names.
    op.execute("""
        CREATE FUNCTION public.custom_access_token_hook(event jsonb)
        RETURNS jsonb
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER SET search_path = ''
        AS $$
        DECLARE
            claims jsonb;
            profile_firm_id uuid;
            profile_role text;
            profile_must_change_password boolean;
        BEGIN
            SELECT firm_id, role, must_change_password
                INTO profile_firm_id, profile_role, profile_must_change_password
                FROM public.profiles
                WHERE id = (event ->> 'user_id')::uuid;

            claims := event -> 'claims';
            IF jsonb_typeof(claims -> 'app_metadata') IS NULL THEN
                claims := jsonb_set(claims, '{app_metadata}', '{}'::jsonb);
            END IF;

            claims := jsonb_set(claims, '{app_metadata,firm_id}', to_jsonb(profile_firm_id));
            claims := jsonb_set(claims, '{app_metadata,role}', to_jsonb(profile_role));
            claims := jsonb_set(
                claims,
                '{app_metadata,must_change_password}',
                to_jsonb(profile_must_change_password)
            );

            event := jsonb_set(event, '{claims}', claims);
            RETURN event;
        END;
        $$
    """)

    op.execute("GRANT EXECUTE ON FUNCTION public.custom_access_token_hook TO supabase_auth_admin")
    op.execute(
        "REVOKE EXECUTE ON FUNCTION public.custom_access_token_hook "
        "FROM authenticated, anon, public"
    )
    # The hook function reads `profiles` as supabase_auth_admin, a role with no RLS-scoping context
    # of its own — matches the grant shape in custom-access-token-hook.md's own admin-role example.
    op.execute("GRANT SELECT ON public.profiles TO supabase_auth_admin")


def downgrade() -> None:
    op.execute("REVOKE SELECT ON public.profiles FROM supabase_auth_admin")
    op.execute("DROP FUNCTION IF EXISTS public.custom_access_token_hook(jsonb)")
