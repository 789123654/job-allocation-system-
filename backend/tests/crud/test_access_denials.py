"""Real SQLite-backed tests for access_denials writes — same reasoning as
tests/crud/test_employee_audit_log.py: route-level tests monkeypatch crud.record_access_denial
itself (tests/api/routes/test_tasks.py) or use a MagicMock session, so the actual write (and its
CHECK-constraint-shaped literal values) is only proven against a real session here.
"""

from collections.abc import Generator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine, select

from app import crud
from app.api.deps import require_owner
from app.models import AccessDenial, Notification, Profile, Task

_FIRM_ID = uuid4()


@pytest.fixture
def session() -> Generator[Session]:
    engine = create_engine("sqlite://")
    tables = [
        Profile.__table__,  # pyright: ignore[reportAttributeAccessIssue]
        Task.__table__,  # pyright: ignore[reportAttributeAccessIssue]
        Notification.__table__,  # pyright: ignore[reportAttributeAccessIssue]
        AccessDenial.__table__,  # pyright: ignore[reportAttributeAccessIssue]
    ]
    SQLModel.metadata.create_all(engine, tables=tables)  # pyright: ignore[reportUnknownArgumentType]
    with Session(engine) as s:
        yield s


def _profile(**overrides: object) -> Profile:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "firm_id": _FIRM_ID,
        "role": "employee",
        "full_name": "Someone",
        "email": "someone@example.com",
        "is_active": True,
        "must_change_password": False,
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return Profile(**defaults)  # pyright: ignore[reportArgumentType]


def _denials(session: Session) -> list[AccessDenial]:
    return list(session.exec(select(AccessDenial)).all())


def test_get_task_wrong_owner_writes_denial(session: Session) -> None:
    other_employee = uuid4()
    actor = _profile(role="employee")
    task = Task(
        firm_id=_FIRM_ID,
        title="Do the thing",
        assigned_to=other_employee,
        status="assigned",
        created_by=uuid4(),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(task)
    session.commit()
    session.refresh(task)

    result = crud.get_task(session, actor, task.id)

    assert result is None
    rows = _denials(session)
    assert len(rows) == 1
    assert rows[0].actor_id == actor.id
    assert rows[0].resource_type == "task"
    assert rows[0].resource_id == task.id
    assert rows[0].reason == "wrong_owner"


def test_get_task_genuinely_missing_writes_no_denial(session: Session) -> None:
    actor = _profile(role="employee")

    result = crud.get_task(session, actor, uuid4())

    assert result is None
    assert _denials(session) == []


def test_get_notification_wrong_recipient_writes_denial(session: Session) -> None:
    actor = _profile(role="employee")
    notification = Notification(
        firm_id=_FIRM_ID,
        recipient_id=uuid4(),
        type="task_assigned",
        is_read=False,
        created_at=datetime.now(UTC),
    )
    session.add(notification)
    session.commit()
    session.refresh(notification)

    result = crud.get_notification(session, actor, notification.id)

    assert result is None
    rows = _denials(session)
    assert len(rows) == 1
    assert rows[0].resource_type == "notification"
    assert rows[0].resource_id == notification.id
    assert rows[0].reason == "wrong_owner"


def test_require_owner_wrong_role_writes_denial(session: Session) -> None:
    actor = _profile(role="employee")

    with pytest.raises(HTTPException) as exc_info:
        require_owner(actor, session)

    assert exc_info.value.status_code == 403
    rows = _denials(session)
    assert len(rows) == 1
    assert rows[0].resource_type is None
    assert rows[0].resource_id is None
    assert rows[0].reason == "wrong_role"


def test_require_owner_passes_through_for_owner(session: Session) -> None:
    actor = _profile(role="owner")

    result = require_owner(actor, session)

    assert result is actor
    assert _denials(session) == []
