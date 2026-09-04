"""Route-level tests — dependency-overridden, no real DB. `with_idempotency` itself is monkeypatched
to just call its handler directly: its own cache-hit/miss/conflict logic is covered for real in
tests/core/test_idempotency.py against a real SQLite session, not re-tested here against a mock.
"""

from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import crud
from app.api import deps
from app.api.routes import tasks as tasks_route
from app.main import app
from app.models import Task

_FIRM_ID = uuid4()
_OWNER_ID = uuid4()
_EMPLOYEE_ID = uuid4()


def _fake_owner() -> "object":
    from app.models import Profile

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


def _fake_employee() -> "object":
    from app.models import Profile

    return Profile(
        id=_EMPLOYEE_ID,
        firm_id=_FIRM_ID,
        role="employee",
        full_name="Employee",
        email="e@example.com",
        is_active=True,
        must_change_password=False,
        created_at=datetime.now(UTC),
    )


def _pass_through_idempotency(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        tasks_route,
        "with_idempotency",
        lambda session, actor, key, endpoint, body, handler: handler(),
    )


@pytest.fixture
def owner_client(monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient]:
    _pass_through_idempotency(monkeypatch)
    app.dependency_overrides[deps.require_owner] = _fake_owner
    app.dependency_overrides[deps.require_password_set] = _fake_owner
    app.dependency_overrides[deps.get_session] = lambda: MagicMock()
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def employee_client(monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient]:
    _pass_through_idempotency(monkeypatch)
    app.dependency_overrides[deps.require_password_set] = _fake_employee
    app.dependency_overrides[deps.get_session] = lambda: MagicMock()
    yield TestClient(app)
    app.dependency_overrides.clear()


def _fake_task(**overrides: object) -> Task:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "firm_id": _FIRM_ID,
        "job_type_id": None,
        "task_type": "standard",
        "parent_task_id": None,
        "title": "Do the thing",
        "description": None,
        "assigned_to": _EMPLOYEE_ID,
        "deadline": None,
        "status": "assigned",
        "created_by": _OWNER_ID,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
        "last_reassignment_notes": None,
        "last_reassignment_remaining_work": None,
        "last_reassignment_source": None,
        "last_reassignment_at": None,
        "billing_amount": None,
        "billing_recipient": None,
    }
    defaults.update(overrides)
    return Task(**defaults)  # pyright: ignore[reportArgumentType]


def test_create_task_requires_idempotency_key_header(owner_client: TestClient) -> None:
    response = owner_client.post("/tasks", json={"title": "Do the thing"})
    assert response.status_code == 422  # FastAPI's own required-header validation


def test_create_task_returns_it(owner_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(crud, "create_task", lambda *a, **kw: _fake_task())

    response = owner_client.post(
        "/tasks",
        json={"title": "Do the thing"},
        headers={"Idempotency-Key": "key-1"},
    )

    assert response.status_code == 201
    assert response.json()["title"] == "Do the thing"


def test_get_nonexistent_task_is_404(
    owner_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(crud, "get_task", lambda *a, **kw: None)

    response = owner_client.get(f"/tasks/{uuid4()}")

    assert response.status_code == 404


def test_owner_cannot_submit_task(
    owner_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # "Assigned employee only" (API_SPEC.md) — an Owner can see the task but can't act on it.
    task = _fake_task()
    monkeypatch.setattr(crud, "get_task", lambda *a, **kw: task)
    denials: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        crud, "record_access_denial", lambda *a, **kw: denials.append(a)
    )

    response = owner_client.post(
        f"/tasks/{task.id}/submit", headers={"Idempotency-Key": "key-1"}
    )

    assert response.status_code == 403
    # (session, actor, resource_type, resource_id, reason) — access_denials wiring, DATA_MODEL.md
    assert len(denials) == 1
    assert denials[0][2:] == ("task", task.id, "not_assignee")


def test_assigned_employee_can_submit_task(
    employee_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _fake_task(assigned_to=_EMPLOYEE_ID, status="assigned")
    monkeypatch.setattr(crud, "get_task", lambda *a, **kw: task)
    monkeypatch.setattr(crud, "submit_task", lambda *a, **kw: _fake_task(status="submitted"))

    response = employee_client.post(
        f"/tasks/{task.id}/submit", headers={"Idempotency-Key": "key-1"}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "submitted"


def test_submit_wrong_state_is_409(
    employee_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _fake_task(assigned_to=_EMPLOYEE_ID, status="completed")
    monkeypatch.setattr(crud, "get_task", lambda *a, **kw: task)

    def _raise(*a: object, **kw: object) -> None:
        raise crud.InvalidTaskStateError

    monkeypatch.setattr(crud, "submit_task", _raise)

    response = employee_client.post(
        f"/tasks/{task.id}/submit", headers={"Idempotency-Key": "key-1"}
    )

    assert response.status_code == 409


def test_update_deadline_nonexistent_task_is_404_not_403(
    owner_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(crud, "get_task", lambda *a, **kw: None)

    response = owner_client.patch(
        f"/tasks/{uuid4()}/deadline", json={"deadline": "2026-12-01T00:00:00Z"}
    )

    assert response.status_code == 404


def test_review_requires_idempotency_key_header(owner_client: TestClient) -> None:
    response = owner_client.post(f"/tasks/{uuid4()}/review", json={"outcome": "approved"})
    assert response.status_code == 422  # FastAPI's own required-header validation


def test_review_approved_returns_updated_task(
    owner_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _fake_task(status="submitted")
    monkeypatch.setattr(crud, "get_task", lambda *a, **kw: task)
    monkeypatch.setattr(
        crud,
        "create_task_review",
        lambda *a, **kw: (None, _fake_task(status="completed")),
    )

    response = owner_client.post(
        f"/tasks/{task.id}/review",
        json={"outcome": "approved", "notes": "looks good"},
        headers={"Idempotency-Key": "key-1"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_review_wrong_state_is_409(
    owner_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _fake_task(status="in_progress")
    monkeypatch.setattr(crud, "get_task", lambda *a, **kw: task)

    def _raise(*a: object, **kw: object) -> None:
        raise crud.InvalidTaskStateError

    monkeypatch.setattr(crud, "create_task_review", _raise)

    response = owner_client.post(
        f"/tasks/{task.id}/review",
        json={"outcome": "approved"},
        headers={"Idempotency-Key": "key-1"},
    )

    assert response.status_code == 409


def test_review_reassigned_without_remaining_work_is_422(owner_client: TestClient) -> None:
    # Business_Logic_Security_Cheat_Sheet.md "Validate Combinations" — the field is required for
    # this specific outcome, enforced by TaskReviewCreate's own model_validator.
    response = owner_client.post(
        f"/tasks/{uuid4()}/review",
        json={"outcome": "reassigned"},
        headers={"Idempotency-Key": "key-1"},
    )
    assert response.status_code == 422


def test_review_approved_rejects_billing_fields(owner_client: TestClient) -> None:
    response = owner_client.post(
        f"/tasks/{uuid4()}/review",
        json={"outcome": "approved", "billing_amount": 100},
        headers={"Idempotency-Key": "key-1"},
    )
    assert response.status_code == 422


def test_create_issue_requires_idempotency_key_header(employee_client: TestClient) -> None:
    task = _fake_task(assigned_to=_EMPLOYEE_ID, status="in_progress")
    response = employee_client.post(f"/tasks/{task.id}/issues", json={"description": "Blocked"})
    assert response.status_code == 422


def test_assigned_employee_can_raise_issue(
    employee_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _fake_task(assigned_to=_EMPLOYEE_ID, status="in_progress")
    monkeypatch.setattr(crud, "get_task", lambda *a, **kw: task)
    from app.models import Issue

    issue = Issue(
        id=uuid4(),
        firm_id=_FIRM_ID,
        task_id=task.id,
        raised_by=_EMPLOYEE_ID,
        description="Blocked",
        status="open",
        created_at=datetime.now(UTC),
    )
    monkeypatch.setattr(crud, "create_issue", lambda *a, **kw: issue)

    response = employee_client.post(
        f"/tasks/{task.id}/issues",
        json={"description": "Blocked"},
        headers={"Idempotency-Key": "key-1"},
    )

    assert response.status_code == 201
    assert response.json()["status"] == "open"


def test_owner_cannot_raise_issue(
    owner_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _fake_task(status="in_progress")
    monkeypatch.setattr(crud, "get_task", lambda *a, **kw: task)
    denials: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        crud, "record_access_denial", lambda *a, **kw: denials.append(a)
    )

    response = owner_client.post(
        f"/tasks/{task.id}/issues",
        json={"description": "Blocked"},
        headers={"Idempotency-Key": "key-1"},
    )

    assert response.status_code == 403
    assert len(denials) == 1
    assert denials[0][2:] == ("task", task.id, "not_assignee")


def test_employee_list_is_scoped_server_side(
    employee_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # crud.list_tasks does the actual scoping (tested there implicitly via the role branch);
    # this just confirms the route passes the real actor through rather than trusting a query
    # param the client could set.
    seen_actor_roles = []

    def _list_tasks(session: object, actor: object, *a: object, **kw: object) -> list[Task]:
        seen_actor_roles.append(getattr(actor, "role", None))
        return []

    monkeypatch.setattr(crud, "list_tasks", _list_tasks)

    response = employee_client.get("/tasks")

    assert response.status_code == 200
    assert seen_actor_roles == ["employee"]
