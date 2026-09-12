"""Real SQLite-backed correctness test for list_tasks' ordering (added 2026-09-13, code-review
finding): the query previously had no ORDER BY at all, so which rows land in a `limit`-bounded
page — and in what order — had no guarantee. This is the one place that checks the ordering is
actually deterministic and newest-first, matching list_notifications' own precedent (crud.py's
existing `.order_by(col(Notification.created_at).desc())`), and that offset/limit pagination over
that order doesn't drop or duplicate rows.
"""

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app import crud
from app.models import Profile, Task


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


def _task(session: Session, owner: Profile, title: str, created_at: datetime) -> Task:
    task = Task(
        id=uuid4(),
        firm_id=owner.firm_id,
        title=title,
        created_by=owner.id,
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(task)
    session.commit()
    return task


def test_list_tasks_orders_newest_first_regardless_of_insertion_order(session: Session) -> None:
    owner = _owner(session)
    now = datetime.now(UTC)
    # Insert deliberately out of chronological order — if list_tasks had no ORDER BY, the return
    # order would just mirror insertion order, not the newest-first order this test demands.
    middle = _task(session, owner, "Middle", now - timedelta(hours=1))
    newest = _task(session, owner, "Newest", now)
    oldest = _task(session, owner, "Oldest", now - timedelta(hours=2))

    results = crud.list_tasks(session, owner, 0, 50, None, None, None, None)

    assert [t.id for t in results] == [newest.id, middle.id, oldest.id]


def test_list_tasks_pagination_is_stable_across_pages(session: Session) -> None:
    owner = _owner(session)
    now = datetime.now(UTC)
    tasks = [_task(session, owner, f"Task {i}", now - timedelta(minutes=i)) for i in range(5)]

    page1 = crud.list_tasks(session, owner, 0, 2, None, None, None, None)
    page2 = crud.list_tasks(session, owner, 2, 2, None, None, None, None)

    # Without a deterministic order, offset/limit pagination has no guarantee against the same
    # row appearing on two pages or a row never appearing at all.
    seen_ids = [t.id for t in page1] + [t.id for t in page2]
    assert seen_ids == [tasks[0].id, tasks[1].id, tasks[2].id, tasks[3].id]
