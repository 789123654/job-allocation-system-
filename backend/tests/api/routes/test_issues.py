"""Route-level tests — dependency-overridden, no real DB. `with_idempotency` monkeypatched to a
pass-through, same reasoning as tests/api/routes/test_tasks.py.
"""

from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import crud
from app.api import deps
from app.api.routes import issues as issues_route
from app.main import app
from app.models import Issue, Profile

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
def owner_client(monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient]:
    monkeypatch.setattr(
        issues_route,
        "with_idempotency",
        lambda session, actor, key, endpoint, body, handler: handler(),
    )
    app.dependency_overrides[deps.require_owner] = _fake_owner
    app.dependency_overrides[deps.require_password_set] = _fake_owner
    app.dependency_overrides[deps.get_session] = lambda: MagicMock()
    yield TestClient(app)
    app.dependency_overrides.clear()


def _fake_issue(**overrides: object) -> Issue:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "firm_id": _FIRM_ID,
        "task_id": uuid4(),
        "raised_by": uuid4(),
        "description": "Blocked",
        "status": "open",
        "resolution_type": None,
        "resolution_notes": None,
        "resolved_by": None,
        "resolved_at": None,
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return Issue(**defaults)  # pyright: ignore[reportArgumentType]


def test_resolve_requires_idempotency_key_header(owner_client: TestClient) -> None:
    response = owner_client.post(
        f"/issues/{uuid4()}/resolve",
        json={"resolution_type": "clarified", "resolution_notes": "explained"},
    )
    assert response.status_code == 422


def test_resolve_nonexistent_issue_is_404(
    owner_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(crud, "get_issue", lambda *a, **kw: None)

    response = owner_client.post(
        f"/issues/{uuid4()}/resolve",
        json={"resolution_type": "clarified", "resolution_notes": "explained"},
        headers={"Idempotency-Key": "key-1"},
    )

    assert response.status_code == 404


def test_resolve_clarified_returns_resolved_issue(
    owner_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    issue = _fake_issue()
    monkeypatch.setattr(crud, "get_issue", lambda *a, **kw: issue)
    monkeypatch.setattr(
        crud, "resolve_issue", lambda *a, **kw: _fake_issue(status="resolved")
    )

    response = owner_client.post(
        f"/issues/{issue.id}/resolve",
        json={"resolution_type": "clarified", "resolution_notes": "explained scope"},
        headers={"Idempotency-Key": "key-1"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "resolved"


def test_resolve_already_resolved_is_409(
    owner_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    issue = _fake_issue(status="resolved")
    monkeypatch.setattr(crud, "get_issue", lambda *a, **kw: issue)

    def _raise(*a: object, **kw: object) -> None:
        raise crud.InvalidIssueStateError

    monkeypatch.setattr(crud, "resolve_issue", _raise)

    response = owner_client.post(
        f"/issues/{issue.id}/resolve",
        json={"resolution_type": "clarified", "resolution_notes": "too late"},
        headers={"Idempotency-Key": "key-1"},
    )

    assert response.status_code == 409


def test_deadline_adjusted_without_new_deadline_is_422(owner_client: TestClient) -> None:
    # Business_Logic_Security_Cheat_Sheet.md "Validate Combinations", same as TaskReviewCreate.
    response = owner_client.post(
        f"/issues/{uuid4()}/resolve",
        json={"resolution_type": "deadline_adjusted", "resolution_notes": "extended"},
        headers={"Idempotency-Key": "key-1"},
    )
    assert response.status_code == 422


def test_clarified_with_new_deadline_is_422(owner_client: TestClient) -> None:
    response = owner_client.post(
        f"/issues/{uuid4()}/resolve",
        json={
            "resolution_type": "clarified",
            "resolution_notes": "explained",
            "new_deadline": "2026-12-01T00:00:00Z",
        },
        headers={"Idempotency-Key": "key-1"},
    )
    assert response.status_code == 422
