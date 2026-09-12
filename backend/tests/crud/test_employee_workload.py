"""Real SQLite-backed correctness test for list_employees' new pending_job_count (PRD §2.4,
added 2026-09-13 for the Owner Dashboard slice) — tests/crud/test_query_counts.py already guards
this function's query *count*, but never checked the actual *value* is right. This is the one
place that does.
"""

from collections.abc import Generator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app import crud
from app.models import Profile, Task

_FIRM_ID = uuid4()


@pytest.fixture
def session() -> Generator[Session]:
    engine = create_engine("sqlite://")
    tables = [
        Profile.__table__,  # pyright: ignore[reportAttributeAccessIssue]
        Task.__table__,  # pyright: ignore[reportAttributeAccessIssue]
    ]
    SQLModel.metadata.create_all(engine, tables=tables)  # pyright: ignore[reportUnknownArgumentType]
    with Session(engine) as s:
        yield s


def _employee(session: Session, **overrides: object) -> Profile:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "firm_id": _FIRM_ID,
        "role": "employee",
        "full_name": "Employee",
        "email": "employee@example.com",
        "is_active": True,
        "must_change_password": True,
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    employee = Profile(**defaults)  # pyright: ignore[reportArgumentType]
    session.add(employee)
    session.commit()
    return employee


def _task(session: Session, assigned_to: object, status: str, **overrides: object) -> None:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid4(),
        "firm_id": _FIRM_ID,
        "job_type_id": None,
        "task_type": "standard",
        "parent_task_id": None,
        "title": "A task",
        "description": None,
        "assigned_to": assigned_to,
        "deadline": None,
        "status": status,
        "created_by": uuid4(),
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    session.add(Task(**defaults))  # pyright: ignore[reportArgumentType]
    session.commit()


def test_pending_job_count_counts_only_assigned_and_in_progress(session: Session) -> None:
    # Profile isn't hashable (a plain SQLModel/Pydantic table model, no __hash__ defined) — found
    # by actually running this test, not assumed; keyed by id instead of using Profile as a dict
    # key.
    busy = _employee(session, email="busy@example.com")
    idle = _employee(session, email="idle@example.com")
    _task(session, busy.id, "assigned")
    _task(session, busy.id, "in_progress")
    _task(session, busy.id, "completed")  # not pending — must not count
    _task(session, idle.id, "submitted")  # not pending either — awaiting review, not active work

    results = {profile.id: count for profile, count in crud.list_employees(session, 0, 50)}

    assert results[busy.id] == 2
    assert results[idle.id] == 0


def test_employee_with_zero_tasks_gets_zero_not_null(session: Session) -> None:
    lonely = _employee(session, email="lonely@example.com")

    results = {profile.id: count for profile, count in crud.list_employees(session, 0, 50)}

    assert results[lonely.id] == 0
