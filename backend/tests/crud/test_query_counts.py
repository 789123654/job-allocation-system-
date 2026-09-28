"""N+1 guardrails for the read paths.

A mocked session can't catch an N+1 — you need real SQL emission to count. These run against
in-memory SQLite (same pattern as test_notification_generation.py), call the crud list functions
directly, and count the statements that actually hit the driver.

Two kinds of assertion:
  - the plain list functions (tasks, employees, job types) must be exactly ONE query no matter how
    many rows exist — they're a single `select().all()`, and anything else is a regression.
  - `list_notifications` runs the lazy deadline-scan first (crud._ensure_deadline_notifications),
    which today does one dedup SELECT per task via `_create_notification_if_missing`. That's linear
    in task count. At the current target (2-4 firms, ~30 users — ca-tool-project-scope) an owner
    poll is roughly tasks x owners point-lookups every 30-60s; tolerable but no longer negligible,
    so a single bulk `SELECT ... WHERE task_id IN (...)` up front (flattening it to O(1)) is worth
    doing as its own small change. This test's job is narrower: stop it getting *worse* than linear
    (a new per-row query, or a nested scan going quadratic).
"""

from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from app import crud
from app.models import Issue, JobType, Notification, Profile, Task

_FIRM_ID = uuid4()
_COUNTED_VERBS = ("SELECT", "INSERT", "UPDATE", "DELETE")


@pytest.fixture
def session() -> Generator[Session]:
    engine = create_engine("sqlite://")
    tables = [
        Task.__table__,  # pyright: ignore[reportAttributeAccessIssue]
        Issue.__table__,  # pyright: ignore[reportAttributeAccessIssue]
        Profile.__table__,  # pyright: ignore[reportAttributeAccessIssue]
        Notification.__table__,  # pyright: ignore[reportAttributeAccessIssue]
        JobType.__table__,  # pyright: ignore[reportAttributeAccessIssue]
    ]
    SQLModel.metadata.create_all(engine, tables=tables)  # pyright: ignore[reportUnknownArgumentType]
    # Match core/db.py's real session — expire_on_commit=False, so an actor Profile loaded before a
    # commit isn't silently re-fetched when a crud function reads actor.role/actor.id afterwards.
    # Without this the fixture's own seed commits would inflate the count with reloads that never
    # happen in a real request.
    with Session(engine, expire_on_commit=False) as s:
        yield s


@contextmanager
def count_queries(session: Session) -> Generator[list[str]]:
    """Records every SELECT/INSERT/UPDATE/DELETE sent to the driver inside the block."""
    seen: list[str] = []
    bind = session.get_bind()

    def _hook(
        _conn: object,
        _cursor: object,
        statement: str,
        _params: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if statement.lstrip().split(None, 1)[0].upper() in _COUNTED_VERBS:
            seen.append(statement)

    event.listen(bind, "before_cursor_execute", _hook)
    try:
        yield seen
    finally:
        event.remove(bind, "before_cursor_execute", _hook)


def _owner(session: Session, firm_id: object = _FIRM_ID) -> Profile:
    owner = Profile(
        id=uuid4(),
        firm_id=firm_id,  # pyright: ignore[reportArgumentType]
        role="owner",
        full_name="Owner",
        email=f"owner-{uuid4()}@example.com",
        is_active=True,
        must_change_password=False,
        created_at=datetime.now(UTC),
    )
    session.add(owner)
    session.commit()
    return owner


def _seed_tasks(
    session: Session, owner: Profile, n: int, *, deadline: datetime | None = None
) -> None:
    now = datetime.now(UTC)
    for i in range(n):
        session.add(
            Task(
                firm_id=owner.firm_id,
                title=f"Task {i}",
                status="assigned",
                deadline=deadline,
                created_by=owner.id,
                created_at=now,
                updated_at=now,
            )
        )
    session.commit()


def _seed_employees(session: Session, firm_id: object, n: int) -> None:
    for i in range(n):
        session.add(
            Profile(
                id=uuid4(),
                firm_id=firm_id,  # pyright: ignore[reportArgumentType]
                role="employee",
                full_name=f"Employee {i}",
                email=f"emp-{uuid4()}@example.com",
                is_active=True,
                must_change_password=False,
                created_at=datetime.now(UTC),
            )
        )
    session.commit()


def _seed_job_types(session: Session, owner: Profile, n: int) -> None:
    now = datetime.now(UTC)
    for i in range(n):
        session.add(
            JobType(firm_id=owner.firm_id, name=f"Type {i}", created_by=owner.id, created_at=now)
        )
    session.commit()


def test_list_tasks_is_one_query_regardless_of_row_count(session: Session) -> None:
    owner = _owner(session)
    _seed_tasks(session, owner, 3)
    with count_queries(session) as few:
        crud.list_tasks(session, owner, 0, 50, None, None, None, None)
    _seed_tasks(session, owner, 20)
    with count_queries(session) as many:
        crud.list_tasks(session, owner, 0, 50, None, None, None, None)
    assert len(few) == 1
    assert len(many) == 1


def test_list_employees_is_one_query_regardless_of_row_count(session: Session) -> None:
    owner = _owner(session)
    _seed_employees(session, _FIRM_ID, 3)
    with count_queries(session) as few:
        crud.list_employees(session, owner, 0, 50)
    _seed_employees(session, _FIRM_ID, 20)
    with count_queries(session) as many:
        crud.list_employees(session, owner, 0, 50)
    assert len(few) == 1
    assert len(many) == 1


def test_list_job_types_is_one_query_regardless_of_row_count(session: Session) -> None:
    owner = _owner(session)
    _seed_job_types(session, owner, 3)
    with count_queries(session) as few:
        crud.list_job_types(session, owner, 0, 50)
    _seed_job_types(session, owner, 20)
    with count_queries(session) as many:
        crud.list_job_types(session, owner, 0, 50)
    assert len(few) == 1
    assert len(many) == 1


def test_list_notifications_deadline_scan_is_flat_in_task_count(session: Session) -> None:
    """After the bulk-prefetch refactor (_scan_firm_deadlines) the dedup scan is a fixed set of
    queries — tasks, owners, existing notifications, then list_notifications' own final SELECT —
    regardless of how many deadline tasks the firm has. Measured on a *second* poll so the
    first poll's new-notification INSERTs aren't in the way.
    """
    past = datetime.now(UTC) - timedelta(days=2)

    owner_small = _owner(session, firm_id=uuid4())
    _seed_tasks(session, owner_small, 2, deadline=past)
    crud.list_notifications(session, owner_small, 0, 50, unread_only=False)  # warm: creates rows
    with count_queries(session) as small:
        crud.list_notifications(session, owner_small, 0, 50, unread_only=False)

    owner_large = _owner(session, firm_id=uuid4())
    _seed_tasks(session, owner_large, 20, deadline=past)
    crud.list_notifications(session, owner_large, 0, 50, unread_only=False)
    with count_queries(session) as large:
        crud.list_notifications(session, owner_large, 0, 50, unread_only=False)

    assert len(large) == len(small), (
        f"notifications scan: {len(small)} queries for 2 tasks, {len(large)} for 20 — "
        "grew with task count, the per-task N+1 is back"
    )
