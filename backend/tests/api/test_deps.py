"""get_current_profile (api/deps.py) is the one place in this codebase that queries the DB
outside crud.py — deliberately sidelined during the Phase 3 audit as out of scope for the
"routes call crud.py only" rule (CODING_STRUCTURE.md §5 scopes that rule to vertical slices, not
shared auth plumbing). But sidelined-from-that-rule isn't the same as tested: every route test
overrides get_current_profile away via dependency_overrides (tests/api/routes/*.py), so its own
set_config/profile-lookup logic has never actually run in any test, unlike everything in crud.py.

Needs a real Postgres — set_config()/current_setting() don't exist on SQLite (same constraint as
tests/crud/test_rls_isolation.py; same skip pattern, same env vars, already wired in CI).
"""

import os
import time
from collections.abc import Generator
from types import SimpleNamespace
from uuid import UUID, uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import Engine, create_engine, text
from sqlmodel import Session

from app.api import deps
from app.core import security

_MIGRATIONS_URL = os.environ.get("TEST_MIGRATIONS_DATABASE_URL")
_APP_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not (_MIGRATIONS_URL and _APP_URL),
    reason="needs a real Postgres — set TEST_MIGRATIONS_DATABASE_URL/TEST_DATABASE_URL (CI does)",
)

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUBLIC_KEY = _PRIVATE_KEY.public_key()


def _make_token(sub: str, firm_id: str) -> str:
    claims = {
        "sub": sub,
        "aud": "authenticated",
        "iss": security.settings.JWT_ISSUER,
        "exp": int(time.time()) + 3600,
        "app_metadata": {"firm_id": firm_id, "role": "owner"},
    }
    return jwt.encode(claims, _PRIVATE_KEY, algorithm="RS256")


def _bearer(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


@pytest.fixture(autouse=True)
def _mock_jwks(  # pyright: ignore[reportUnusedFunction] — autouse pytest fixture, run by pytest
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Same approach as tests/core/test_security.py — swap the real JWKS network call for a fixed
    # key, so this test exercises get_current_profile's own logic, not Supabase's availability.
    monkeypatch.setattr(
        security._jwks_client,  # pyright: ignore[reportPrivateUsage]
        "get_signing_key_from_jwt",
        lambda token: SimpleNamespace(key=_PUBLIC_KEY),
    )


@pytest.fixture
def app_engine() -> Generator[Engine]:
    assert _APP_URL is not None  # guaranteed by pytestmark's skipif above
    engine = create_engine(_APP_URL)
    yield engine
    engine.dispose()


@pytest.fixture
def profile(request: pytest.FixtureRequest) -> Generator[tuple[UUID, UUID]]:
    """Inserted with the superuser connection (bypasses RLS by construction), same reasoning as
    test_rls_isolation.py's two_firms fixture — planting fixture data isn't what's under test.
    """
    assert _MIGRATIONS_URL is not None  # guaranteed by pytestmark's skipif above
    is_active = getattr(request, "param", True)
    admin_engine = create_engine(_MIGRATIONS_URL)
    firm_id, profile_id = uuid4(), uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO firms (id, name, plan, status) VALUES (:id, 'x', 'free', 'active')"),
            {"id": firm_id},
        )
        conn.execute(
            text(
                "INSERT INTO profiles (id, firm_id, role, full_name, email, is_active) "
                "VALUES (:pid, :fid, 'owner', 'x', :email, :active)"
            ),
            {
                "pid": profile_id,
                "fid": firm_id,
                "email": f"{profile_id}@example.com",
                "active": is_active,
            },
        )
    yield firm_id, profile_id
    with admin_engine.begin() as conn:
        conn.execute(text("DELETE FROM profiles WHERE firm_id = :fid"), {"fid": firm_id})
        conn.execute(text("DELETE FROM firms WHERE id = :fid"), {"fid": firm_id})
    admin_engine.dispose()


def test_valid_token_returns_profile_and_sets_tenant_context(
    app_engine: Engine, profile: tuple[UUID, UUID]
) -> None:
    firm_id, profile_id = profile
    token = _make_token(sub=str(profile_id), firm_id=str(firm_id))

    with Session(app_engine) as session:
        result = deps.get_current_profile(session, _bearer(token))
        assert result.id == profile_id

        # The actual point of this test: set_config really ran against this connection, not just
        # "didn't crash" — app.current_tenant is what every downstream RLS policy checks.
        # execute(), not exec() — same reason as deps.py's own set_config call: a bare SELECT
        # whose return value needs .scalar(), which SQLModel's exec() doesn't support.
        current_tenant = session.execute(  # pyright: ignore[reportDeprecated]
            text("SELECT current_setting('app.current_tenant', true)")
        ).scalar()
        assert current_tenant == str(firm_id)


@pytest.mark.parametrize("profile", [False], indirect=True)
def test_inactive_profile_is_rejected(app_engine: Engine, profile: tuple[UUID, UUID]) -> None:
    firm_id, profile_id = profile
    token = _make_token(sub=str(profile_id), firm_id=str(firm_id))

    credentials = _bearer(token)
    with Session(app_engine) as session:
        # SonarQube S5778: only one call inside pytest.raises, so a bug that made _bearer() raise
        # instead couldn't be mistaken for the code under test failing correctly.
        with pytest.raises(HTTPException) as exc_info:
            deps.get_current_profile(session, credentials)
        assert exc_info.value.status_code == 401


def test_unknown_profile_id_is_rejected(app_engine: Engine) -> None:
    # A structurally valid, correctly-signed token for a profile that doesn't exist — e.g. a
    # deleted account whose token hasn't expired yet.
    token = _make_token(sub=str(uuid4()), firm_id=str(uuid4()))
    credentials = _bearer(token)

    with Session(app_engine) as session:
        with pytest.raises(HTTPException) as exc_info:
            deps.get_current_profile(session, credentials)
        assert exc_info.value.status_code == 401
