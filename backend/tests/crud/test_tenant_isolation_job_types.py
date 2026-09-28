from collections.abc import Generator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app import crud
from app.models import JobType, Profile


@pytest.fixture
def session() -> Generator[Session]:
    engine = create_engine("sqlite://")
    tables = [
        Profile.__table__,  # pyright: ignore[reportAttributeAccessIssue]
        JobType.__table__,  # pyright: ignore[reportAttributeAccessIssue]
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


def _job_type(session: Session, firm_id: UUID, created_by: UUID, **overrides: object) -> JobType:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "firm_id": firm_id,
        "name": "Test Type",
        "is_active": True,
        "created_by": created_by,
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    job_type = JobType(**defaults)  # pyright: ignore[reportArgumentType]
    session.add(job_type)
    session.commit()
    return job_type


def test_get_job_type_cross_tenant_isolation(session: Session) -> None:
    """Test that get_job_type returns None when job_type_id belongs to a different firm."""
    actor_a = _profile(session)
    firm_b_id = uuid4()
    actor_b = _profile(session, firm_id=firm_b_id)

    job_type_b = _job_type(session, firm_id=firm_b_id, created_by=actor_b.id, name="Firm B Job")

    # Actor A attempts to get Job Type B (should return None)
    result = crud.get_job_type(session, actor_a, job_type_b.id)
    assert result is None, "get_job_type must not return job types from other firms"


def test_get_job_type_same_tenant_access(session: Session) -> None:
    """Test that get_job_type returns the JobType when called by an actor in the same firm."""
    actor = _profile(session)
    job_type = _job_type(session, firm_id=actor.firm_id, created_by=actor.id, name="Firm A Job")

    result = crud.get_job_type(session, actor, job_type.id)
    assert result is not None, "get_job_type must return job types from the actor's firm"
    assert result.id == job_type.id
    assert result.firm_id == actor.firm_id


def test_list_job_types_cross_tenant_isolation(session: Session) -> None:
    """Test that list_job_types only returns job types from the actor's firm."""
    actor_a = _profile(session)
    firm_b_id = uuid4()
    actor_b = _profile(session, firm_id=firm_b_id)

    # Seed job types for both firms
    job_type_a1 = _job_type(
        session, firm_id=actor_a.firm_id, created_by=actor_a.id, name="Firm A Job 1"
    )
    job_type_a2 = _job_type(
        session, firm_id=actor_a.firm_id, created_by=actor_a.id, name="Firm A Job 2"
    )
    job_type_b = _job_type(session, firm_id=firm_b_id, created_by=actor_b.id, name="Firm B Job")

    # Actor A lists job types
    result = crud.list_job_types(session, actor_a, offset=0, limit=10)

    # Must contain only Firm A's job types, never Firm B's
    result_ids = {jt.id for jt in result}
    assert len(result) == 2, "list_job_types must return only the actor's firm's job types"
    assert job_type_a1.id in result_ids
    assert job_type_a2.id in result_ids
    assert job_type_b.id not in result_ids, "must never include job types from other firms"
