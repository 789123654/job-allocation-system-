from collections.abc import Generator
from datetime import UTC, datetime
from uuid import UUID, uuid4

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


def _profile(session: Session, **overrides: object) -> Profile:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "firm_id": uuid4(),
        "role": "owner",
        "full_name": "Test",
        "email": f"{uuid4()}@example.com",
        "is_active": True,
        "must_change_password": False,
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    profile = Profile(**defaults)  # pyright: ignore[reportArgumentType]
    session.add(profile)
    session.commit()
    return profile


def _task(session: Session, firm_id: UUID, created_by: UUID, **overrides: object) -> Task:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": uuid4(),
        "firm_id": firm_id,
        "title": "Test Task",
        "status": "created",
        "created_by": created_by,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    task = Task(**defaults)  # pyright: ignore[reportArgumentType]
    session.add(task)
    session.commit()
    return task


class TestGetTaskTenantIsolation:
    def test_get_task_returns_none_for_different_firm(self, session: Session) -> None:
        """get_task returns None when task belongs to a different firm (IDOR test)."""
        # Create actor in Firm A
        firm_a_id = uuid4()
        actor_a = _profile(session, firm_id=firm_a_id)

        # Create a task in Firm B
        firm_b_id = uuid4()
        task_b = _task(session, firm_id=firm_b_id, created_by=uuid4())

        # Actor from Firm A tries to access Firm B's task
        result = crud.get_task(session, actor_a, task_b.id)

        assert result is None, "Should not return task from different firm"

    def test_get_task_returns_task_for_same_firm(self, session: Session) -> None:
        """get_task returns the Task when it belongs to the actor's firm."""
        # Create actor and task in same firm
        firm_id = uuid4()
        actor = _profile(session, firm_id=firm_id)
        task = _task(session, firm_id=firm_id, created_by=actor.id)

        # Actor retrieves their own firm's task
        result = crud.get_task(session, actor, task.id)

        assert result is not None, "Should return task from same firm"
        assert result.id == task.id
        assert result.firm_id == firm_id


class TestListTasksTenantIsolation:
    def test_list_tasks_returns_only_same_firm(self, session: Session) -> None:
        """list_tasks returns only tasks belonging to the actor's firm."""
        # Create two firms with actors
        firm_a_id = uuid4()
        firm_b_id = uuid4()
        actor_a = _profile(session, firm_id=firm_a_id)

        # Create tasks in both firms
        task_a1 = _task(session, firm_id=firm_a_id, created_by=actor_a.id, title="Task A1")
        task_a2 = _task(session, firm_id=firm_a_id, created_by=actor_a.id, title="Task A2")
        task_b1 = _task(session, firm_id=firm_b_id, created_by=uuid4(), title="Task B1")

        # Actor A lists tasks (no filters)
        result = crud.list_tasks(
            session, actor_a, offset=0, limit=100,
            status_filter=None, assigned_to_filter=None,
            job_type_id_filter=None, task_type_filter=None
        )

        result_ids = {task.id for task in result}

        # Must contain Firm A's tasks
        assert task_a1.id in result_ids, "Should include own firm's tasks"
        assert task_a2.id in result_ids, "Should include own firm's tasks"

        # Must NOT contain Firm B's task
        assert task_b1.id not in result_ids, "Should never return tasks from different firm"

        # All returned tasks must be from Firm A
        assert all(task.firm_id == firm_a_id for task in result), "tasks must belong to own firm"
