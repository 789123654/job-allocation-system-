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
from app.models import Task

_FIRM_ID = uuid4()


@pytest.fixture
def session() -> Generator[Session]:
    engine = create_engine("sqlite://")
    table = Task.__table__  # pyright: ignore[reportAttributeAccessIssue]
    SQLModel.metadata.create_all(engine, tables=[table])  # pyright: ignore[reportUnknownArgumentType]
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
