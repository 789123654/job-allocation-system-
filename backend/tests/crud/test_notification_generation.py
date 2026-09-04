"""Real SQLite-backed tests for the notification side effects (crud._notify/_notify_owners) and
the lazy deadline-scan (crud._ensure_deadline_notifications) — a mocked session would only prove
a write happened, not that the right recipient/type/dedup actually holds.
"""

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app import crud
from app.models import AccessDenial, Issue, Notification, Profile, Task

_FIRM_ID = uuid4()


@pytest.fixture
def session() -> Generator[Session]:
    engine = create_engine("sqlite://")
    tables = [
        Task.__table__,  # pyright: ignore[reportAttributeAccessIssue]
        Issue.__table__,  # pyright: ignore[reportAttributeAccessIssue]
        Profile.__table__,  # pyright: ignore[reportAttributeAccessIssue]
        Notification.__table__,  # pyright: ignore[reportAttributeAccessIssue]
        AccessDenial.__table__,  # pyright: ignore[reportAttributeAccessIssue]
    ]
    SQLModel.metadata.create_all(engine, tables=tables)  # pyright: ignore[reportUnknownArgumentType]
    with Session(engine) as s:
        yield s


def _owner(session: Session, **overrides: object) -> Profile:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "firm_id": _FIRM_ID,
        "role": "owner",
        "full_name": "Owner",
        "email": f"owner-{uuid4()}@example.com",
        "is_active": True,
        "must_change_password": False,
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    owner = Profile(**defaults)  # pyright: ignore[reportArgumentType]
    session.add(owner)
    session.commit()
    return owner


def _employee(session: Session, **overrides: object) -> Profile:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "firm_id": _FIRM_ID,
        "role": "employee",
        "full_name": "Employee",
        "email": f"employee-{uuid4()}@example.com",
        "is_active": True,
        "must_change_password": False,
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    employee = Profile(**defaults)  # pyright: ignore[reportArgumentType]
    session.add(employee)
    session.commit()
    return employee


def _notifications_for(session: Session, recipient_id: object) -> list[Notification]:
    return list(
        session.exec(select(Notification).where(Notification.recipient_id == recipient_id)).all()
    )


def test_create_task_notifies_assignee(session: Session) -> None:
    owner = _owner(session)
    employee = _employee(session)

    task = crud.create_task(session, owner, "Do the thing", None, None, employee.id, None)
    session.commit()

    notifications = _notifications_for(session, employee.id)
    assert len(notifications) == 1
    assert notifications[0].type == "task_assigned"
    assert notifications[0].task_id == task.id


def test_create_task_unassigned_notifies_nobody(session: Session) -> None:
    owner = _owner(session)

    crud.create_task(session, owner, "Do the thing", None, None, None, None)
    session.commit()

    all_notifications = list(session.exec(select(Notification)).all())
    assert all_notifications == []


def test_submit_task_notifies_all_owners(session: Session) -> None:
    owner1 = _owner(session)
    owner2 = _owner(session)
    employee = _employee(session)
    task = Task(
        firm_id=_FIRM_ID,
        title="Do the thing",
        assigned_to=employee.id,
        status="assigned",
        created_by=owner1.id,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(task)
    session.commit()

    crud.submit_task(session, task)
    session.commit()

    for owner in (owner1, owner2):
        notifications = _notifications_for(session, owner.id)
        assert len(notifications) == 1
        assert notifications[0].type == "task_submitted"


def test_create_issue_notifies_owners(session: Session) -> None:
    owner = _owner(session)
    employee = _employee(session)
    task = Task(
        firm_id=_FIRM_ID,
        title="Do the thing",
        assigned_to=employee.id,
        status="in_progress",
        created_by=owner.id,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(task)
    session.commit()

    issue = crud.create_issue(session, employee, task, "Blocked")
    session.commit()

    notifications = _notifications_for(session, owner.id)
    assert len(notifications) == 1
    assert notifications[0].type == "issue_raised"
    assert notifications[0].issue_id == issue.id


def _task_with_deadline(
    session: Session, owner: Profile, employee: Profile, deadline: datetime
) -> Task:
    task = Task(
        firm_id=_FIRM_ID,
        title="Do the thing",
        assigned_to=employee.id,
        deadline=deadline,
        status="assigned",
        created_by=owner.id,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(task)
    session.commit()
    return task


def test_owner_sees_overdue_and_urgent_deadline_notifications(session: Session) -> None:
    owner = _owner(session)
    employee = _employee(session)
    now = datetime.now(UTC)
    _task_with_deadline(session, owner, employee, now - timedelta(days=1))  # overdue
    _task_with_deadline(session, owner, employee, now + timedelta(hours=12))  # within 1 day
    _task_with_deadline(session, owner, employee, now + timedelta(days=10))  # not close yet

    notifications = crud.list_notifications(session, owner, 0, 20, unread_only=False)

    types = sorted(n.type for n in notifications)
    assert types == ["task_deadline_1_day", "task_overdue"]


def test_employee_sees_own_overdue_and_approaching_deadline_notifications(
    session: Session,
) -> None:
    owner = _owner(session)
    employee = _employee(session)
    other_employee = _employee(session)
    now = datetime.now(UTC)
    _task_with_deadline(session, owner, employee, now - timedelta(hours=1))  # overdue
    _task_with_deadline(session, owner, employee, now + timedelta(days=2))  # approaching
    # Another employee's overdue task must never appear in this employee's list (no broadcast).
    _task_with_deadline(session, owner, other_employee, now - timedelta(hours=1))

    notifications = crud.list_notifications(session, employee, 0, 20, unread_only=False)

    types = sorted(n.type for n in notifications)
    assert types == ["task_deadline_approaching", "task_overdue_own"]


def test_deadline_scan_does_not_duplicate_on_repeated_polls(session: Session) -> None:
    owner = _owner(session)
    employee = _employee(session)
    _task_with_deadline(session, owner, employee, datetime.now(UTC) - timedelta(days=1))

    crud.list_notifications(session, owner, 0, 20, unread_only=False)
    crud.list_notifications(session, owner, 0, 20, unread_only=False)
    notifications = crud.list_notifications(session, owner, 0, 20, unread_only=False)

    assert len(notifications) == 1


def test_mark_notification_read(session: Session) -> None:
    owner = _owner(session)
    employee = _employee(session)
    task = crud.create_task(session, owner, "Do the thing", None, None, employee.id, None)
    session.commit()
    notification = _notifications_for(session, employee.id)[0]

    updated = crud.mark_notification_read(session, notification)

    assert updated.is_read is True
    assert task.id == notification.task_id  # sanity: same task the notification points at


def test_get_notification_returns_none_for_another_recipient(session: Session) -> None:
    owner = _owner(session)
    employee = _employee(session)
    other_employee = _employee(session)
    crud.create_task(session, owner, "Do the thing", None, None, employee.id, None)
    session.commit()
    notification = _notifications_for(session, employee.id)[0]

    assert crud.get_notification(session, other_employee, notification.id) is None
    assert crud.get_notification(session, employee, notification.id) is not None
