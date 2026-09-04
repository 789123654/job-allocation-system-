"""RLS can't be meaningfully tested against a mock (CODING_STRUCTURE.md §2) — these run against a
real, disposable Postgres. Locally that means nothing (skipped) unless you point
TEST_MIGRATIONS_DATABASE_URL / TEST_DATABASE_URL at one yourself; in CI it's the postgres:16
service container in .github/workflows/ci.yml, migrated fresh every run.

Two required pre-launch checks, verbatim from ARCHITECTURE.md §5:
  1. fastapi_app must never carry BYPASSRLS (a config-drift regrant would be exactly as silent
     as the original gap that made this project pick a dedicated role in the first place).
  2. A direct-ID cross-tenant read/update against another firm's row must affect zero rows —
     listing-endpoint tests alone don't prove isolation.
"""

import os
from collections.abc import Generator
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, Engine, create_engine, text

_MIGRATIONS_URL = os.environ.get("TEST_MIGRATIONS_DATABASE_URL")
_APP_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not (_MIGRATIONS_URL and _APP_URL),
    reason="needs a real Postgres — set TEST_MIGRATIONS_DATABASE_URL/TEST_DATABASE_URL (CI does)",
)


def _set_tenant(conn: Connection, firm_id: object) -> None:
    conn.execute(text("SELECT set_config('app.current_tenant', :fid, true)"), {"fid": str(firm_id)})


@pytest.fixture
def two_firms(request: pytest.FixtureRequest) -> Generator[tuple[dict[str, UUID], dict[str, UUID]]]:
    """Inserted with the superuser connection (bypasses RLS by construction) — this fixture's job
    is to plant fixture data across two tenants, not to exercise the isolation being tested.
    """
    assert _MIGRATIONS_URL is not None  # guaranteed by pytestmark's skipif above
    admin_engine = create_engine(_MIGRATIONS_URL)
    firm_a, firm_b = {"id": uuid4(), "profile_id": uuid4()}, {"id": uuid4(), "profile_id": uuid4()}
    with admin_engine.begin() as conn:
        for firm in (firm_a, firm_b):
            conn.execute(
                text(
                    "INSERT INTO firms (id, name, plan, status) VALUES (:id, 'x', 'free', 'active')"
                ),
                {"id": firm["id"]},
            )
            conn.execute(
                text(
                    "INSERT INTO profiles (id, firm_id, role, full_name, email) "
                    "VALUES (:pid, :fid, 'owner', 'x', :email)"
                ),
                {
                    "pid": firm["profile_id"],
                    "fid": firm["id"],
                    "email": f"{firm['id']}@example.com",
                },
            )
    yield firm_a, firm_b
    with admin_engine.begin() as conn:
        for firm in (firm_a, firm_b):
            conn.execute(text("DELETE FROM profiles WHERE firm_id = :fid"), {"fid": firm["id"]})
            conn.execute(text("DELETE FROM firms WHERE id = :fid"), {"fid": firm["id"]})
    admin_engine.dispose()


@pytest.fixture
def app_engine() -> Generator[Engine]:
    assert _APP_URL is not None  # guaranteed by pytestmark's skipif above
    engine = create_engine(_APP_URL)
    yield engine
    engine.dispose()


def test_fastapi_app_does_not_bypass_rls(app_engine: Engine) -> None:
    with app_engine.connect() as conn:
        query = "SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user"
        result = conn.execute(text(query))
        assert result.scalar() is False


def test_cross_tenant_read_returns_zero_rows(
    app_engine: Engine, two_firms: tuple[dict[str, UUID], dict[str, UUID]]
) -> None:
    firm_a, firm_b = two_firms
    with app_engine.connect() as conn:
        _set_tenant(conn, firm_a["id"])
        result = conn.execute(
            text("SELECT * FROM profiles WHERE id = :pid"), {"pid": firm_b["profile_id"]}
        )
        assert result.fetchall() == []


def test_cross_tenant_update_affects_zero_rows(
    app_engine: Engine, two_firms: tuple[dict[str, UUID], dict[str, UUID]]
) -> None:
    firm_a, firm_b = two_firms
    with app_engine.begin() as conn:
        _set_tenant(conn, firm_a["id"])
        result = conn.execute(
            text("UPDATE profiles SET full_name = 'pwned' WHERE id = :pid"),
            {"pid": firm_b["profile_id"]},
        )
        assert result.rowcount == 0
