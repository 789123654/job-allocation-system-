"""The canary's expected statuses, checked against the REAL API and a REAL Postgres.

The blind canary tests use a fake API that answers per the canary's own spec table — they prove the
canary compares correctly, not that its table matches what the application actually returns. This
runs `ops.canary.run_canary` through the real app + real auth chain + RLS over two seeded firms:
- a correct app passes every one of the 20 checks (so the canary won't cry wolf in production);
- a config that makes a cross-tenant probe actually SUCCEED (firm B's ids pointing at firm A's
  objects) is reported as violations by the real API's real answers (so it can't be blind to a
  leak).

Needs a real Postgres — same skip pattern as tests/api/test_authz_regression.py.
"""

import os
import time
from collections.abc import Generator
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.core import security
from app.main import app
from ops import canary

_MIGRATIONS_URL = os.environ.get("TEST_MIGRATIONS_DATABASE_URL")
_APP_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.authz,
    pytest.mark.skipif(
        not (_MIGRATIONS_URL and _APP_URL),
        reason="needs a real Postgres — TEST_MIGRATIONS_DATABASE_URL/TEST_DATABASE_URL (CI does)",
    ),
]

_FIRM_SCOPED_TABLES = (
    "notifications",
    "access_denials",
    "audit_log",
    "task_reviews",
    "issues",
    "idempotency_keys",
    "tasks",
    "job_types",
    "profiles",
)

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUBLIC_KEY = _PRIVATE_KEY.public_key()


def _token(sub: UUID, firm_id: UUID, role: str) -> str:
    claims = {
        "sub": str(sub),
        "aud": "authenticated",
        "iss": security.settings.JWT_ISSUER,
        "exp": int(time.time()) + 3600,
        "app_metadata": {"firm_id": str(firm_id), "role": role},
    }
    return jwt.encode(claims, _PRIVATE_KEY, algorithm="RS256")


@pytest.fixture(autouse=True)
def _mock_jwks(  # pyright: ignore[reportUnusedFunction]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        security._jwks_client,  # pyright: ignore[reportPrivateUsage]
        "get_signing_key_from_jwt",
        lambda token: SimpleNamespace(key=_PUBLIC_KEY),
    )


def _seed_firm(conn: Any) -> dict[str, str]:
    """One firm: an owner, two employees, a task per employee, a job type, an owner notification.
    Returns the canary's per-firm config entry (tokens minted for the real profiles)."""
    firm, owner, emp1, emp2 = uuid4(), uuid4(), uuid4(), uuid4()
    conn.execute(
        text("INSERT INTO firms (id, name, plan, status) VALUES (:id, 'canary', 'free', 'active')"),
        {"id": firm},
    )
    for pid, role in ((owner, "owner"), (emp1, "employee"), (emp2, "employee")):
        conn.execute(
            text(
                "INSERT INTO profiles "
                "(id, firm_id, role, full_name, email, is_active, must_change_password) "
                "VALUES (:pid, :fid, :role, 'x', :email, true, false)"
            ),
            {"pid": pid, "fid": firm, "role": role, "email": f"{pid}@example.com"},
        )
    task_ids: list[UUID] = [
        conn.execute(
            text(
                "INSERT INTO tasks (firm_id, title, status, created_by, assigned_to) "
                "VALUES (:fid, 'T', 'assigned', :owner, :emp) RETURNING id"
            ),
            {"fid": firm, "owner": owner, "emp": emp},
        ).scalar_one()
        for emp in (emp1, emp2)
    ]
    job_type = conn.execute(
        text(
            "INSERT INTO job_types (firm_id, name, created_by) "
            "VALUES (:fid, 'GST', :o) RETURNING id"
        ),
        {"fid": firm, "o": owner},
    ).scalar_one()
    notification = conn.execute(
        text(
            "INSERT INTO notifications (firm_id, recipient_id, type, task_id) "
            "VALUES (:fid, :o, 'task_submitted', :tid) RETURNING id"
        ),
        {"fid": firm, "o": owner, "tid": task_ids[0]},
    ).scalar_one()
    return {
        "firm_id": str(firm),
        "owner_token": _token(owner, firm, "owner"),
        "employee_token": _token(emp1, firm, "employee"),
        "task_id": str(task_ids[0]),
        "other_employee_task_id": str(task_ids[1]),  # emp2's: emp1 must not be able to read it
        "job_type_id": str(job_type),
        "notification_id": str(notification),
    }


@pytest.fixture
def two_firm_config() -> Generator[dict[str, Any]]:
    assert _MIGRATIONS_URL is not None
    engine = create_engine(_MIGRATIONS_URL)
    with engine.begin() as conn:
        firms = {"alpha": _seed_firm(conn), "beta": _seed_firm(conn)}
    yield {"firms": firms}
    with engine.begin() as conn:
        for entry in firms.values():
            for table in _FIRM_SCOPED_TABLES:
                conn.execute(
                    text(f"DELETE FROM {table} WHERE firm_id = :fid"),  # noqa: S608
                    {"fid": entry["firm_id"]},
                )
            conn.execute(text("DELETE FROM firms WHERE id = :fid"), {"fid": entry["firm_id"]})
    engine.dispose()


def _strip_firm_ids(config: dict[str, Any]) -> dict[str, Any]:
    """The canary's config has no firm_id field; keep the fixture's for cleanup only."""
    return {
        "firms": {
            label: {k: v for k, v in entry.items() if k != "firm_id"}
            for label, entry in config["firms"].items()
        }
    }


def test_the_real_api_passes_every_canary_check(two_firm_config: dict[str, Any]) -> None:
    with TestClient(app) as client:
        report = canary.run_canary(client, _strip_firm_ids(two_firm_config))
    assert report.violations == []
    assert report.errors == []
    assert report.checks_run == report.expected_checks == 20
    assert report.ok


def test_a_real_cross_tenant_success_is_reported_not_missed(
    two_firm_config: dict[str, Any],
) -> None:
    # Point beta's object ids at ALPHA's real objects: now "alpha -> beta" probes are really
    # alpha's owner acting on alpha's own rows, so the API rightly answers 200/2xx — exactly what
    # a genuine cross-tenant leak would look like to the canary.
    config = _strip_firm_ids(two_firm_config)
    alpha = config["firms"]["alpha"]
    for key in ("task_id", "job_type_id", "notification_id"):
        config["firms"]["beta"][key] = alpha[key]
    with TestClient(app) as client:
        report = canary.run_canary(client, config)
    assert not report.ok
    flagged = {v.check for v in report.violations}
    assert "cross_tenant_task_read:alpha->beta" in flagged
    assert "cross_tenant_task_read_employee:alpha->beta" in flagged
    assert "cross_tenant_task_deadline_patch:alpha->beta" in flagged
    assert "cross_tenant_job_type_patch:alpha->beta" in flagged
    assert "cross_tenant_notification_patch:alpha->beta" in flagged
    assert "cross_tenant_task_list_leak:alpha->beta" in flagged
    # ...and the checks that were NOT compromised still pass: no collateral noise.
    assert not any(check.endswith(":beta->alpha") for check in flagged)


def test_a_clean_canary_run_changes_no_tenant_rows(two_firm_config: dict[str, Any]) -> None:
    assert _MIGRATIONS_URL is not None
    engine = create_engine(_MIGRATIONS_URL)

    def counts() -> dict[str, int]:
        with engine.connect() as conn:
            return {
                table: conn.execute(
                    text(f"SELECT count(*) FROM {table}")  # noqa: S608
                ).scalar_one()
                for table in ("tasks", "job_types", "notifications", "profiles")
            }

    before = counts()
    with TestClient(app) as client:
        canary.run_canary(client, _strip_firm_ids(two_firm_config))
    assert counts() == before
    engine.dispose()
