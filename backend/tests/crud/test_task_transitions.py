"""Real SQLite-backed tests for the submit_task/mark_task_billed state-transition logic — a
mocked session would only prove the mock was called, not that the `SELECT ... FOR UPDATE` lock
query and the state check actually run correctly against a real row. Same reasoning and pattern
as tests/core/test_idempotency.py. SQLite ignores `.with_for_update()` (no real row locking), so
this covers the single-caller correctness path, not concurrent-race behavior itself — that's a
Postgres-only property, exercised for real only in CI/production, not unit-testable on SQLite.
"""

from collections.abc import Generator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app import crud
from app.models import Notification, Profile, Task

_FIRM_ID = uuid4()


@pytest.fixture
def session() -> Generator[Session]:
    engine = create_engine("sqlite://")
    # Profile/Notification needed too — submit_task now notifies owners (crud._notify_owners).
    tables = [Task.__table__, Profile.__table__, Notification.__table__]  # pyright: ignore[reportAttributeAccessIssue]
    SQLModel.metadata.create_all(engine, tables=tables)  # pyright: ignore[reportUnknownArgumentType]
    with Session(engine) as s:
        yield s


def _task(session: Session, **overrides: object) -> Task:
    defaults: dict[str, object] = {
        "firm_id": _FIRM_ID,
        "title": "Do the thing",
        "assigned_to": uuid4(),
        "status": "assigned",
        "task_type": "standard",
        "created_by": uuid4(),
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    task = Task(**defaults)  # pyright: ignore[reportArgumentType]
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


def test_submit_task_transitions_from_assigned(session: Session) -> None:
    task = _task(session, status="assigned")

    updated = crud.submit_task(session, task)

    assert updated.status == "submitted"


def test_submit_task_wrong_state_raises(session: Session) -> None:
    task = _task(session, status="completed")

    with pytest.raises(crud.InvalidTaskStateError):
        crud.submit_task(session, task)


def test_mark_task_billed_requires_billing_type(session: Session) -> None:
    task = _task(session, status="assigned", task_type="standard")

    with pytest.raises(crud.InvalidTaskStateError):
        crud.mark_task_billed(session, task)


def test_mark_task_billed_transitions_billing_task(session: Session) -> None:
    task = _task(session, status="in_progress", task_type="billing")

    updated = crud.mark_task_billed(session, task)

    assert updated.status == "billed"


def _profile(session: Session, **overrides: object) -> Profile:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "firm_id": _FIRM_ID,
        "role": "employee",
        "full_name": "Employee",
        "email": "e@example.com",
        "is_active": True,
        "must_change_password": False,
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    profile = Profile(**defaults)  # pyright: ignore[reportArgumentType]
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile


def test_create_task_rejects_nonexistent_assignee(session: Session) -> None:
    owner = _profile(session, role="owner")

    with pytest.raises(crud.UnknownAssigneeError):
        crud.create_task(session, owner, "Do the thing", None, None, uuid4(), None)


def test_create_task_rejects_inactive_assignee(session: Session) -> None:
    owner = _profile(session, role="owner")
    inactive_employee = _profile(session, is_active=False)

    with pytest.raises(crud.UnknownAssigneeError):
        crud.create_task(session, owner, "Do the thing", None, None, inactive_employee.id, None)


def test_create_task_rejects_owner_as_assignee(session: Session) -> None:
    owner = _profile(session, role="owner")
    other_owner = _profile(session, role="owner")

    with pytest.raises(crud.UnknownAssigneeError):
        crud.create_task(session, owner, "Do the thing", None, None, other_owner.id, None)


def test_create_task_accepts_active_employee_assignee(session: Session) -> None:
    owner = _profile(session, role="owner")
    employee = _profile(session)

    task = crud.create_task(session, owner, "Do the thing", None, None, employee.id, None)

    assert task.assigned_to == employee.id


_OTHER_FIRM_ID = uuid4()


def test_create_task_rejects_cross_firm_owner(session: Session) -> None:
    # Proves _validate_assignee's firm_id filter itself is doing the work, not just the
    # role/is_active checks — a different firm's owner must be rejected even though (in
    # isolation) an owner-role profile is what test_create_task_rejects_owner_as_assignee
    # already covers same-firm.
    owner = _profile(session, role="owner")
    other_firm_owner = _profile(session, firm_id=_OTHER_FIRM_ID, role="owner")

    with pytest.raises(crud.UnknownAssigneeError):
        crud.create_task(session, owner, "Do the thing", None, None, other_firm_owner.id, None)


def test_create_task_rejects_cross_firm_employee(session: Session) -> None:
    owner = _profile(session, role="owner")
    other_firm_employee = _profile(session, firm_id=_OTHER_FIRM_ID)

    with pytest.raises(crud.UnknownAssigneeError):
        crud.create_task(session, owner, "Do the thing", None, None, other_firm_employee.id, None)
