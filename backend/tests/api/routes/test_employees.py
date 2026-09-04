"""Route-level tests — dependency-overridden, no real DB (RLS/tenant-isolation tests live
separately in tests/crud/test_rls_isolation.py, since those need a real Postgres).
"""

from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from supabase_auth.errors import AuthApiError

from app import crud
from app.api import deps
from app.api.routes import employees as employees_route
from app.main import app
from app.models import Profile

_FIRM_ID = uuid4()
_OWNER_ID = uuid4()


def _fake_owner() -> Profile:
    return Profile(
        id=_OWNER_ID,
        firm_id=_FIRM_ID,
        role="owner",
        full_name="Owner",
        email="owner@example.com",
        is_active=True,
        must_change_password=False,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient]:
    monkeypatch.setattr(
        employees_route,
        "with_idempotency",
        lambda session, actor, key, endpoint, body, handler: handler(),
    )
    app.dependency_overrides[deps.require_owner] = _fake_owner
    app.dependency_overrides[deps.get_session] = lambda: MagicMock()
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_create_employee_returns_password_once(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    new_id = uuid4()
    monkeypatch.setattr(crud, "create_employee", lambda *a, **kw: (new_id, "temp-pw-123"))

    body_in = {"full_name": "Jane Doe", "email": "jane@example.com"}
    response = client.post("/employees", json=body_in)

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == str(new_id)
    assert body["generated_password"] == "temp-pw-123"


def test_create_employee_duplicate_email_is_409(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise(*a: object, **kw: object) -> None:
        raise AuthApiError("email address already registered", 422, None)

    monkeypatch.setattr(crud, "create_employee", _raise)

    response = client.post("/employees", json={"full_name": "Jane Doe", "email": "dup@example.com"})

    assert response.status_code == 409
    # Supabase's own error text must never reach the client verbatim (API_SPEC.md §1 Rule 177).
    assert "email address already registered" not in response.text


def test_update_nonexistent_employee_is_404_not_403(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(crud, "get_employee", lambda *a, **kw: None)

    response = client.patch(f"/employees/{uuid4()}", json={"is_active": False})

    assert response.status_code == 404


def test_reset_password_returns_password_once(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    employee_id = uuid4()
    fake_employee = Profile(
        id=employee_id,
        firm_id=_FIRM_ID,
        role="employee",
        full_name="Jane Doe",
        email="jane@example.com",
        is_active=True,
        must_change_password=False,
        created_at=datetime.now(UTC),
    )
    monkeypatch.setattr(crud, "get_employee", lambda *a, **kw: fake_employee)
    monkeypatch.setattr(crud, "reset_employee_password", lambda *a, **kw: "new-temp-pw")

    response = client.post(
        f"/employees/{employee_id}/reset-password", headers={"Idempotency-Key": "key-1"}
    )

    assert response.status_code == 200
    assert response.json()["generated_password"] == "new-temp-pw"


def test_reset_password_requires_idempotency_key_header(client: TestClient) -> None:
    response = client.post(f"/employees/{uuid4()}/reset-password")
    assert response.status_code == 422  # FastAPI's own required-header validation


def test_non_owner_is_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_employee_actor() -> Profile:
        return Profile(
            id=uuid4(),
            firm_id=_FIRM_ID,
            role="employee",
            full_name="Employee",
            email="e@example.com",
            is_active=True,
            must_change_password=False,
            created_at=datetime.now(UTC),
        )

    # require_owner itself is the thing under test here — not overridden, only its own
    # dependency (require_password_set) is, so the real role check actually runs.
    app.dependency_overrides[deps.require_password_set] = _fake_employee_actor
    app.dependency_overrides[deps.get_session] = lambda: MagicMock()
    try:
        client = TestClient(app)
        response = client.get("/employees")
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()
