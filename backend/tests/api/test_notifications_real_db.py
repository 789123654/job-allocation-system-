"""PATCH /notifications/{id}/read against a REAL Postgres, for a notification that points at a task.

Found 2026-09-19 by running the tenant-isolation canary against the real API (ops/canary.py,
tests/ops/test_canary_real_api.py): the route committed the read flag and THEN looked up the task
title, so that lookup ran after `set_config('app.current_tenant', ..., true)`'s transaction had
ended — no tenant context, so RLS's `current_setting(...)::uuid` cast raised `invalid input syntax
for type uuid: ""` and the client got a 500 (or, on a never-warmed pooled connection, silently a
null title). It is the exact bug class of 2026-09-08 (crud.py's module docstring) at a call site
that class's fix never reached, because tests/api/routes/test_notifications.py mocks `crud` and so
never ran a real query after the commit.

Needs a real Postgres — same skip pattern as tests/api/test_authz_regression.py.
"""

import os
import time
from collections.abc import Generator
from dataclasses import dataclass
from types import SimpleNamespace
from uuid import UUID, uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.core import security
from app.main import app

_MIGRATIONS_URL = os.environ.get("TEST_MIGRATIONS_DATABASE_URL")
_APP_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.authz,
    pytest.mark.skipif(
        not (_MIGRATIONS_URL and _APP_URL),
        reason="needs a real Postgres — TEST_MIGRATIONS_DATABASE_URL/TEST_DATABASE_URL (CI does)",
    ),
]

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUBLIC_KEY = _PRIVATE_KEY.public_key()


@dataclass
class _Seeded:
    notification_id: UUID
    token: str


@pytest.fixture(autouse=True)
def _mock_jwks(  # pyright: ignore[reportUnusedFunction]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        security._jwks_client,  # pyright: ignore[reportPrivateUsage]
        "get_signing_key_from_jwt",
        lambda token: SimpleNamespace(key=_PUBLIC_KEY),
    )


@pytest.fixture
def seeded() -> Generator[_Seeded]:
    assert _MIGRATIONS_URL is not None
    engine = create_engine(_MIGRATIONS_URL)
    firm, owner = uuid4(), uuid4()
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO firms (id, name, plan, status) VALUES (:id, 'x', 'free', 'active')"),
            {"id": firm},
        )
        conn.execute(
            text(
                "INSERT INTO profiles "
                "(id, firm_id, role, full_name, email, is_active, must_change_password) "
                "VALUES (:pid, :fid, 'owner', 'x', :email, true, false)"
            ),
            {"pid": owner, "fid": firm, "email": f"{owner}@example.com"},
        )
        task = conn.execute(
            text(
                "INSERT INTO tasks (firm_id, title, status, created_by, assigned_to) "
                "VALUES (:fid, 'Quarterly GST return', 'assigned', :o, :o) RETURNING id"
            ),
            {"fid": firm, "o": owner},
        ).scalar_one()
        notification = conn.execute(
            text(
                "INSERT INTO notifications (firm_id, recipient_id, type, task_id) "
                "VALUES (:fid, :o, 'task_submitted', :tid) RETURNING id"
            ),
            {"fid": firm, "o": owner, "tid": task},
        ).scalar_one()
    token = jwt.encode(
        {
            "sub": str(owner),
            "aud": "authenticated",
            "iss": security.settings.JWT_ISSUER,
            "exp": int(time.time()) + 3600,
            "app_metadata": {"firm_id": str(firm), "role": "owner"},
        },
        _PRIVATE_KEY,
        algorithm="RS256",
    )
    yield _Seeded(notification_id=notification, token=token)
    with engine.begin() as conn:
        for table in ("notifications", "tasks", "profiles"):
            conn.execute(text(f"DELETE FROM {table} WHERE firm_id = :fid"), {"fid": firm})  # noqa: S608
        conn.execute(text("DELETE FROM firms WHERE id = :fid"), {"fid": firm})
    engine.dispose()


def test_mark_read_on_a_task_notification_returns_200_with_the_task_title(
    seeded: _Seeded,
) -> None:
    headers = {"Authorization": f"Bearer {seeded.token}"}
    with TestClient(app, raise_server_exceptions=False) as client:
        # Warm a pooled connection with a tenant context first: the failure needs a connection
        # that has already run `set_config(..., true)` once (its setting then reads '' not NULL).
        assert client.get("/notifications", headers=headers).status_code == 200
        response = client.patch(f"/notifications/{seeded.notification_id}/read", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["is_read"] is True
    assert body["task_title"] == "Quarterly GST return"
