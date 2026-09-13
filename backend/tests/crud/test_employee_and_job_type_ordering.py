"""Real SQLite-backed correctness test for list_employees/list_job_types' ordering (added
2026-09-13, code-review finding): both queries had no ORDER BY at all, the exact bug already found
and fixed on list_tasks (test_task_ordering.py) but not backported to these two closest siblings —
so which rows land in a `limit`-bounded page, and in what order, had no guarantee.
"""

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app import crud
from app.models import JobType, Profile, Task


@pytest.fixture
def session() -> Generator[Session]:
    engine = create_engine("sqlite://")
    tables = [
        Profile.__table__,  # pyright: ignore[reportAttributeAccessIssue]
        Task.__table__,  # pyright: ignore[reportAttributeAccessIssue]
        JobType.__table__,  # pyright: ignore[reportAttributeAccessIssue]
    ]
    SQLModel.metadata.create_all(engine, tables=tables)  # pyright: ignore[reportUnknownArgumentType]
    with Session(engine) as s:
        yield s


def _owner(session: Session) -> Profile:
    owner = Profile(
        id=uuid4(),
        firm_id=uuid4(),
        role="owner",
        full_name="Owner",
        email="owner@example.com",
        is_active=True,
        must_change_password=False,
        created_at=datetime.now(UTC),
    )
    session.add(owner)
    session.commit()
    return owner


def _employee(session: Session, owner: Profile, name: str, created_at: datetime) -> Profile:
    employee = Profile(
        id=uuid4(),
        firm_id=owner.firm_id,
        role="employee",
        full_name=name,
        email=f"{name.lower()}@example.com",
        is_active=True,
        must_change_password=False,
        created_at=created_at,
    )
    session.add(employee)
    session.commit()
    return employee


def _job_type(session: Session, owner: Profile, name: str, created_at: datetime) -> JobType:
    job_type = JobType(
        id=uuid4(),
        firm_id=owner.firm_id,
        name=name,
        created_by=owner.id,
        created_at=created_at,
    )
    session.add(job_type)
    session.commit()
    return job_type


def test_list_employees_orders_newest_first_regardless_of_insertion_order(session: Session) -> None:
    owner = _owner(session)
    now = datetime.now(UTC)
    # Insert deliberately out of chronological order — if list_employees had no ORDER BY, the
    # return order would just mirror insertion order, not the newest-first order this test demands.
    middle = _employee(session, owner, "Middle", now - timedelta(hours=1))
    newest = _employee(session, owner, "Newest", now)
    oldest = _employee(session, owner, "Oldest", now - timedelta(hours=2))

    results = crud.list_employees(session, 0, 50)

    assert [profile.id for profile, _ in results] == [newest.id, middle.id, oldest.id]


def test_list_job_types_orders_newest_first_regardless_of_insertion_order(session: Session) -> None:
    owner = _owner(session)
    now = datetime.now(UTC)
    middle = _job_type(session, owner, "Middle", now - timedelta(hours=1))
    newest = _job_type(session, owner, "Newest", now)
    oldest = _job_type(session, owner, "Oldest", now - timedelta(hours=2))

    results = crud.list_job_types(session, 0, 50)

    assert [jt.id for jt in results] == [newest.id, middle.id, oldest.id]
