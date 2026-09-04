"""Route-level tests — dependency-overridden, no real DB (RLS/tenant-isolation tests live
separately in tests/crud/test_rls_isolation.py, since those need a real Postgres).
"""

from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import crud
from app.api import deps
from app.main import app
from app.models import JobType, Profile

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


def _fake_employee() -> Profile:
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


@pytest.fixture
def client() -> Generator[TestClient]:
    # Both dependency levels overridden: POST/PATCH use RequireOwnerDep, GET uses ActiveProfileDep
    # (job_types is readable by any authenticated profile, not just Owner — API_SPEC.md §"Job
    # Types") — a fake owner satisfies both since require_owner itself depends on it.
    app.dependency_overrides[deps.require_owner] = _fake_owner
    app.dependency_overrides[deps.require_password_set] = _fake_owner
    app.dependency_overrides[deps.get_session] = lambda: MagicMock()
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_create_job_type_returns_it(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    new_id = uuid4()
    monkeypatch.setattr(
        crud,
        "create_job_type",
        lambda *a, **kw: JobType(
            id=new_id,
            firm_id=_FIRM_ID,
            name="Audit",
            created_by=_OWNER_ID,
            created_at=datetime.now(UTC),
        ),
    )

    response = client.post("/job-types", json={"name": "Audit"})

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == str(new_id)
    assert body["name"] == "Audit"
    assert body["is_active"] is True


def test_create_job_type_duplicate_name_is_409(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise(*a: object, **kw: object) -> None:
        raise crud.DuplicateJobTypeNameError

    monkeypatch.setattr(crud, "create_job_type", _raise)

    response = client.post("/job-types", json={"name": "Audit"})

    assert response.status_code == 409


def test_update_nonexistent_job_type_is_404_not_403(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(crud, "get_job_type", lambda *a, **kw: None)

    response = client.patch(f"/job-types/{uuid4()}", json={"is_active": False})

    assert response.status_code == 404


def test_non_owner_cannot_create_job_type(monkeypatch: pytest.MonkeyPatch) -> None:
    # require_owner itself is under test here — not overridden, only its own dependency is, so
    # the real role check actually runs (same pattern as test_employees.py).
    app.dependency_overrides[deps.require_password_set] = _fake_employee
    app.dependency_overrides[deps.get_session] = lambda: MagicMock()
    try:
        client = TestClient(app)
        response = client.post("/job-types", json={"name": "Audit"})
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_any_authenticated_can_list_job_types(monkeypatch: pytest.MonkeyPatch) -> None:
    # GET is ActiveProfileDep, not RequireOwnerDep — an Employee actor must succeed here, the
    # opposite of the check above (API_SPEC.md: "Both roles need this for task creation/filtering").
    monkeypatch.setattr(crud, "list_job_types", lambda *a, **kw: [])
    app.dependency_overrides[deps.require_password_set] = _fake_employee
    app.dependency_overrides[deps.get_session] = lambda: MagicMock()
    try:
        client = TestClient(app)
        response = client.get("/job-types")
        assert response.status_code == 200
    finally:
        app.dependency_overrides.clear()
