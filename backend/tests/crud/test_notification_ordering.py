"""Real SQLite-backed correctness test for list_notifications' tie-breaking on `created_at`: when
two or more notifications share the exact same timestamp, pagination must still be deterministic
and lossless (every row exactly once across pages), which requires a secondary sort key (`id`)
breaking ties consistently. Mirrors test_task_ordering.py's structure for Task/list_tasks.
"""

from collections.abc import Generator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app import crud
from app.models import Notification, Profile, Task


@pytest.fixture
def session() -> Generator[Session]:
    engine = create_engine("sqlite://")
    tables = [
        Profile.__table__,  # pyright: ignore[reportAttributeAccessIssue]
        Notification.__table__,  # pyright: ignore[reportAttributeAccessIssue]
        # list_notifications calls _ensure_deadline_notifications, which scans tasks — needs the
        # table present even though this test creates no tasks.
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


def _notification(session: Session, owner: Profile, created_at: datetime) -> Notification:
    notification = Notification(
        id=uuid4(),
        firm_id=owner.firm_id,
        recipient_id=owner.id,
        type="task_assigned",
        created_at=created_at,
    )
    session.add(notification)
    session.commit()
    return notification


def test_list_notifications_pagination_is_lossless_with_tied_created_at(session: Session) -> None:
    owner = _owner(session)
    same_time = datetime.now(UTC)
    # All rows share the exact same created_at — if list_notifications only sorted by created_at,
    # pagination order among tied rows would be undefined, and offset/limit pages could skip or
    # duplicate rows depending on the DB's arbitrary tie-break.
    notifications = [_notification(session, owner, same_time) for _ in range(5)]
    expected_ids = {n.id for n in notifications}

    pages = [
        crud.list_notifications(session, owner, offset, 2, False)
        for offset in (0, 2, 4)
    ]
    seen_ids = [n.id for page in pages for n in page]

    assert len(seen_ids) == len(expected_ids)
    assert set(seen_ids) == expected_ids
