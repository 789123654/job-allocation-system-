"""Route-level tests — dependency-overridden, no real DB. The lazy deadline-scan and dedup logic
itself is covered for real in tests/crud/test_notifications.py against a real SQLite session.
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
from app.models import Notification, Profile

_FIRM_ID = uuid4()
_EMPLOYEE_ID = uuid4()


def _fake_employee() -> Profile:
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


@pytest.fixture
def client() -> Generator[TestClient]:
    app.dependency_overrides[deps.require_password_set] = _fake_employee
    app.dependency_overrides[deps.get_session] = lambda: MagicMock()
    yield TestClient(app)
    app.dependency_overrides.clear()


def _fake_notification(**overrides: object) -> Notification:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "firm_id": _FIRM_ID,
        "recipient_id": _EMPLOYEE_ID,
        "type": "task_assigned",
        "task_id": uuid4(),
        "issue_id": None,
        "is_read": False,
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return Notification(**defaults)  # pyright: ignore[reportArgumentType]


def test_list_notifications_returns_them(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(crud, "list_notifications", lambda *a, **kw: [_fake_notification()])

    response = client.get("/notifications")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["type"] == "task_assigned"


def test_list_notifications_defaults_to_unread_only(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}

    def _list_notifications(
        session: object, actor: object, offset: int, limit: int, unread_only: bool
    ) -> list[Notification]:
        seen["unread_only"] = unread_only
        return []

    monkeypatch.setattr(crud, "list_notifications", _list_notifications)

    response = client.get("/notifications")

    assert response.status_code == 200
    assert seen["unread_only"] is True


def test_mark_read_nonexistent_is_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(crud, "get_notification", lambda *a, **kw: None)

    response = client.patch(f"/notifications/{uuid4()}/read")

    assert response.status_code == 404


def test_mark_read_returns_updated_notification(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    notification = _fake_notification(is_read=False)
    monkeypatch.setattr(crud, "get_notification", lambda *a, **kw: notification)
    monkeypatch.setattr(
        crud, "mark_notification_read", lambda *a, **kw: _fake_notification(is_read=True)
    )

    response = client.patch(f"/notifications/{notification.id}/read")

    assert response.status_code == 200
    assert response.json()["is_read"] is True
