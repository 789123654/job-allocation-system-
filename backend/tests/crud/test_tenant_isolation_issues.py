from collections.abc import Generator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app import crud
from app.models import Issue, Profile


@pytest.fixture
def session() -> Generator[Session]:
    engine = create_engine("sqlite://")
    tables = [
        Profile.__table__,  # pyright: ignore[reportAttributeAccessIssue]
        Issue.__table__,  # pyright: ignore[reportAttributeAccessIssue]
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


def _issue(session: Session, firm_id: UUID, raised_by: UUID, **overrides: object) -> Issue:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "firm_id": firm_id,
        "task_id": uuid4(),
        "raised_by": raised_by,
        "description": "Test issue",
        "status": "open",
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    issue = Issue(**defaults)  # pyright: ignore[reportArgumentType]
    session.add(issue)
    session.commit()
    return issue


def test_get_issue_cross_tenant_isolation(session: Session) -> None:
    """get_issue must return None when actor is from a different firm."""
    # Create two profiles in different firms
    actor_firm_a = _profile(session)
    actor_firm_b = _profile(session)

    # Create an issue in Firm A
    issue_in_firm_a = _issue(session, firm_id=actor_firm_a.firm_id, raised_by=actor_firm_a.id)

    # Actor from Firm B should NOT be able to access issue from Firm A
    result = crud.get_issue(session, actor_firm_b, issue_in_firm_a.id)
    assert result is None, "Cross-tenant access should be blocked"


def test_get_issue_same_tenant_access(session: Session) -> None:
    """get_issue must return the issue when actor is from the same firm."""
    # Create a profile
    actor = _profile(session)

    # Create an issue in the same firm
    issue = _issue(session, firm_id=actor.firm_id, raised_by=actor.id)

    # Actor should be able to access their own firm's issue
    result = crud.get_issue(session, actor, issue.id)
    assert result is not None, "Same-tenant access should succeed"
    assert result.id == issue.id
    assert result.firm_id == actor.firm_id
