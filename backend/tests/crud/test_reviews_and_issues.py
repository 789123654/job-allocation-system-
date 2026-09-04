"""Real SQLite-backed tests for create_task_review/create_issue/resolve_issue — same reasoning as
tests/crud/test_task_transitions.py: a mocked session would only prove the mock was called, not
that the outcome branching, the linked-billing-task creation, and the reassignment convergence
actually work against real rows.
"""

from collections.abc import Generator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app import crud
from app.models import Issue, Profile, Task, TaskReview

_FIRM_ID = uuid4()


@pytest.fixture
def session() -> Generator[Session]:
    engine = create_engine("sqlite://")
    tables = [Task.__table__, TaskReview.__table__, Issue.__table__]  # pyright: ignore[reportAttributeAccessIssue]
    SQLModel.metadata.create_all(engine, tables=tables)  # pyright: ignore[reportUnknownArgumentType]
    with Session(engine) as s:
        yield s


def _actor() -> Profile:
    return Profile(
        id=uuid4(),
        firm_id=_FIRM_ID,
        role="owner",
        full_name="Owner",
        email="owner@example.com",
        is_active=True,
        must_change_password=False,
        created_at=datetime.now(UTC),
    )


def _task(session: Session, **overrides: object) -> Task:
    defaults: dict[str, object] = {
        "firm_id": _FIRM_ID,
        "title": "Do the thing",
        "assigned_to": uuid4(),
        "status": "submitted",
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


def test_review_approved_completes_task(session: Session) -> None:
    task = _task(session, status="submitted")
    actor = _actor()

    _, updated = crud.create_task_review(
        session, actor, task, "approved", "looks good", None, None, None, None, None, None
    )
    session.commit()

    assert updated.status == "completed"


def test_review_reassigned_sets_last_reassignment_fields(session: Session) -> None:
    task = _task(session, status="submitted")
    actor = _actor()
    new_employee = uuid4()

    review, updated = crud.create_task_review(
        session,
        actor,
        task,
        "reassigned",
        "needs more work",
        "finish the appendix",
        new_employee,
        None,
        None,
        None,
        None,
    )
    session.commit()

    assert updated.status == "in_progress"
    assert updated.assigned_to == new_employee
    assert updated.last_reassignment_source == "review"
    assert updated.last_reassignment_remaining_work == "finish the appendix"
    assert review.remaining_work_description == "finish the appendix"


def test_review_billing_creates_linked_task(session: Session) -> None:
    task = _task(session, status="submitted")
    actor = _actor()
    employee = uuid4()

    review, updated = crud.create_task_review(
        session,
        actor,
        task,
        "billing",
        None,
        None,
        employee,
        datetime.now(UTC),
        "Invoice the client",
        500.0,
        "Client Co",
    )
    session.commit()

    assert updated.status == "completed"
    assert review.resulting_billing_task_id is not None
    billing_task = session.exec(
        select(Task).where(Task.id == review.resulting_billing_task_id)
    ).one()
    assert billing_task.task_type == "billing"
    assert billing_task.parent_task_id == task.id
    assert billing_task.billing_amount == 500.0


def test_review_wrong_state_raises(session: Session) -> None:
    task = _task(session, status="in_progress")
    actor = _actor()

    with pytest.raises(crud.InvalidTaskStateError):
        crud.create_task_review(
            session, actor, task, "approved", None, None, None, None, None, None, None
        )


def test_create_issue_on_active_task(session: Session) -> None:
    task = _task(session, status="in_progress")
    actor = _actor()

    issue = crud.create_issue(session, actor, task, "Client hasn't sent documents")
    session.commit()

    assert issue.status == "open"
    assert issue.task_id == task.id


def test_create_issue_wrong_state_raises(session: Session) -> None:
    task = _task(session, status="completed")
    actor = _actor()

    with pytest.raises(crud.InvalidTaskStateError):
        crud.create_issue(session, actor, task, "too late")


def _issue(session: Session, task: Task, **overrides: object) -> Issue:
    defaults: dict[str, object] = {
        "firm_id": _FIRM_ID,
        "task_id": task.id,
        "raised_by": uuid4(),
        "description": "Blocked",
        "status": "open",
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    issue = Issue(**defaults)  # pyright: ignore[reportArgumentType]
    session.add(issue)
    session.commit()
    session.refresh(issue)
    return issue


def test_resolve_issue_clarified_does_not_touch_task(session: Session) -> None:
    task = _task(session, status="in_progress")
    issue = _issue(session, task)
    actor = _actor()

    resolved = crud.resolve_issue(session, actor, issue, "clarified", "explained scope", None, None)
    session.commit()
    session.refresh(task)

    assert resolved.status == "resolved"
    assert task.status == "in_progress"


def test_resolve_issue_deadline_adjusted_updates_task(session: Session) -> None:
    task = _task(session, status="in_progress")
    issue = _issue(session, task)
    actor = _actor()
    new_deadline = datetime.now(UTC)

    crud.resolve_issue(session, actor, issue, "deadline_adjusted", "extended", new_deadline, None)
    session.commit()
    session.refresh(task)

    # SQLite (unlike Postgres' timestamptz) drops tzinfo on round-trip — compare instants, not
    # naive-vs-aware equality, which `==` would otherwise fail even when the value is correct.
    assert task.deadline is not None
    assert task.deadline.replace(tzinfo=UTC) == new_deadline


def test_resolve_issue_reassigned_uses_shared_reassignment_path(session: Session) -> None:
    task = _task(session, status="in_progress")
    issue = _issue(session, task)
    actor = _actor()
    new_employee = uuid4()

    crud.resolve_issue(
        session, actor, issue, "reassigned", "give to someone else", None, new_employee
    )
    session.commit()
    session.refresh(task)

    assert task.assigned_to == new_employee
    assert task.last_reassignment_source == "issue"
    assert task.status == "in_progress"


def test_resolve_issue_already_resolved_raises(session: Session) -> None:
    task = _task(session, status="in_progress")
    issue = _issue(session, task, status="resolved")
    actor = _actor()

    with pytest.raises(crud.InvalidIssueStateError):
        crud.resolve_issue(session, actor, issue, "clarified", "too late", None, None)
