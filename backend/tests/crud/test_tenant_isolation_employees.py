from collections.abc import Generator
from datetime import UTC, datetime
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


def _profile(session: Session, **overrides: object) -> Profile:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "firm_id": uuid4(),
        "role": "employee",
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


class TestGetEmployeeTenantIsolation:
    """Test that get_employee respects firm_id isolation."""

    def test_get_employee_different_firm_returns_none(self, session: Session) -> None:
        """Actor in Firm A cannot retrieve employee from Firm B."""
        firm_a_id = uuid4()
        firm_b_id = uuid4()

        actor = _profile(session, firm_id=firm_a_id, role="owner")
        employee_b = _profile(session, firm_id=firm_b_id, role="employee")

        result = crud.get_employee(session, actor, employee_b.id)
        assert result is None

    def test_get_employee_same_firm_returns_profile(self, session: Session) -> None:
        """Actor in Firm A can retrieve their own firm's employee."""
        firm_a_id = uuid4()

        actor = _profile(session, firm_id=firm_a_id, role="owner")
        employee_a = _profile(session, firm_id=firm_a_id, role="employee")

        result = crud.get_employee(session, actor, employee_a.id)
        assert result is not None
        assert result.id == employee_a.id
        assert result.firm_id == firm_a_id


class TestListEmployeesTenantIsolation:
    """Test that list_employees respects firm_id isolation."""

    def test_list_employees_excludes_other_firm(self, session: Session) -> None:
        """list_employees must never include employees from other firms."""
        firm_a_id = uuid4()
        firm_b_id = uuid4()

        actor = _profile(session, firm_id=firm_a_id, role="owner")
        employee_a1 = _profile(session, firm_id=firm_a_id, role="employee", full_name="A1")
        employee_a2 = _profile(session, firm_id=firm_a_id, role="employee", full_name="A2")
        employee_b = _profile(session, firm_id=firm_b_id, role="employee", full_name="B")

        result = crud.list_employees(session, actor, offset=0, limit=100)

        result_ids = {profile.id for profile, _ in result}
        assert employee_a1.id in result_ids
        assert employee_a2.id in result_ids
        assert employee_b.id not in result_ids
