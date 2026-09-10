"""End-to-end auth against a real local Supabase stack (`supabase start` — GoTrue + Postgres).

The `backend` job runs against bare `postgres:17` with a hand-stubbed `auth.users`; it can't
exercise GoTrue, real token issuance, or the JWKS endpoint. These tests fill exactly that gap —
the two auth-schema objects that only exist as migration SQL and have no other coverage:

  * `handle_new_user` (trigger on auth.users)   — provisions the `profiles` row (cb67cdb7538a)
  * `custom_access_token_hook` (claims injector) — puts firm_id/role/must_change_password in the
                                                   JWT's app_metadata (a8e6def15927)

plus one full round-trip: a real GoTrue-issued ES256 token, verified by the app against the real
local JWKS endpoint, all the way through the auth dependency chain to a role-gated route.

Skipped unless `E2E=1` — set only by the `e2e` CI job, which runs `supabase start` then
`alembic upgrade head` first. Never runs in the plain `backend` job.
"""

import json
import os
import uuid
from collections.abc import Generator

import httpx
import pytest
from sqlalchemy import Engine, create_engine, text

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("E2E") != "1",
        reason="needs a local Supabase stack — E2E=1 (set by the `e2e` CI job)",
    ),
]

_SUPABASE_URL = os.environ.get("SUPABASE_URL", "http://127.0.0.1:54321")
_ANON_KEY = os.environ.get("E2E_ANON_KEY", "")
_ADMIN_URL = os.environ.get(
    "TEST_MIGRATIONS_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@127.0.0.1:54322/postgres",
)
_PASSWORD = "e2e-Test-Password-9"  # meets config.toml's minimum_password_length = 8


@pytest.fixture
def admin_engine() -> Generator[Engine]:
    # The supabase superuser connection — bypasses RLS by construction, the same role Alembic and
    # GoTrue's own admin path use. Planting fixture data isn't what's under test here.
    engine = create_engine(_ADMIN_URL)
    yield engine
    engine.dispose()


@pytest.fixture
def firm(admin_engine: Engine) -> Generator[uuid.UUID]:
    firm_id = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO firms (id, name, plan, status) "
                "VALUES (:id, 'E2E', 'free', 'active')"
            ),
            {"id": firm_id},
        )
    yield firm_id
    with admin_engine.begin() as conn:
        for table in ("notifications", "access_denials", "audit_log", "profiles"):
            conn.execute(text(f"DELETE FROM {table} WHERE firm_id = :f"), {"f": firm_id})  # noqa: S608
        conn.execute(text("DELETE FROM firms WHERE id = :f"), {"f": firm_id})


def _password_grant(email: str) -> httpx.Response:
    return httpx.post(
        f"{_SUPABASE_URL}/auth/v1/token",
        params={"grant_type": "password"},
        json={"email": email, "password": _PASSWORD},
        headers={"apikey": _ANON_KEY, "Content-Type": "application/json"},
        timeout=15,
    )


def test_custom_access_token_hook_injects_claims_from_the_profile(admin_engine: Engine) -> None:
    """Pure-SQL check of the hook function — no GoTrue involved. Given a profile row, the hook must
    copy that row's firm_id / role / must_change_password into claims.app_metadata.
    """
    firm_id, user_id = uuid.uuid4(), uuid.uuid4()
    event = {"user_id": str(user_id), "claims": {"app_metadata": {}}}
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO firms (id, name, plan, status) VALUES (:f, 'E2E', 'free', 'active')"),
            {"f": firm_id},
        )
        conn.execute(
            text(
                "INSERT INTO profiles (id, firm_id, role, full_name, email, must_change_password) "
                "VALUES (:u, :f, 'owner', 'Owner', :e, true)"
            ),
            {"u": user_id, "f": firm_id, "e": f"{user_id}@example.com"},
        )
        out = conn.execute(
            text("SELECT public.custom_access_token_hook(CAST(:e AS jsonb))"),
            {"e": json.dumps(event)},
        ).scalar_one()
        conn.execute(text("DELETE FROM profiles WHERE firm_id = :f"), {"f": firm_id})
        conn.execute(text("DELETE FROM firms WHERE id = :f"), {"f": firm_id})

    app_metadata = out["claims"]["app_metadata"]
    assert app_metadata["firm_id"] == str(firm_id)
    assert app_metadata["role"] == "owner"
    assert app_metadata["must_change_password"] is True


def test_admin_provisioned_user_gets_a_working_real_token(
    admin_engine: Engine, firm: uuid.UUID
) -> None:
    """The real chain: Auth Admin API creates a user -> the `on_auth_user_created` trigger writes
    the profile -> a real password-grant login mints an ES256 token whose app_metadata the hook
    filled from that profile -> the app verifies it against the real local JWKS and runs the whole
    auth dependency chain.
    """
    from fastapi.testclient import TestClient

    from app.core.supabase_admin import admin_auth
    from app.main import app

    email = f"{uuid.uuid4()}@example.com"
    created = admin_auth.create_user(
        {
            "email": email,
            "password": _PASSWORD,
            "email_confirm": True,
            "user_metadata": {"firm_id": str(firm), "role": "owner", "full_name": "Owner"},
        }
    )
    user_id = uuid.UUID(created.user.id)

    # 1. the provisioning trigger fired inside the admin-createUser transaction
    with admin_engine.connect() as conn:
        row = conn.execute(
            text("SELECT firm_id, role, must_change_password FROM profiles WHERE id = :u"),
            {"u": user_id},
        ).one()
    assert row.firm_id == firm
    assert row.role == "owner"
    assert row.must_change_password is True

    client = TestClient(app)

    # 2. real login -> real ES256 token; a just-provisioned user is still behind the forced-reset
    #    gate (require_password_set), proven end to end with a genuine token.
    token = _password_grant(email).json()["access_token"]
    blocked = client.get("/employees", headers={"Authorization": f"Bearer {token}"})
    assert blocked.status_code == 403

    # 3. clear the flag, log in again -> the hook reflects the new value, the gate passes, and the
    #    owner-role check passes: a clean 200 through the full chain.
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE profiles SET must_change_password = false WHERE id = :u"), {"u": user_id}
        )
    fresh_token = _password_grant(email).json()["access_token"]
    ok = client.get("/employees", headers={"Authorization": f"Bearer {fresh_token}"})
    assert ok.status_code == 200

    admin_auth.delete_user(str(user_id))
