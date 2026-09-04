"""Real SQLite-backed tests for the employee lifecycle's audit_log writes — same reasoning as
tests/crud/test_task_transitions.py: route-level tests (tests/api/routes/test_employees.py)
monkeypatch crud functions wholesale, so _write_audit_log never actually runs there. These tests
exercise create_employee/set_employee_active/reset_employee_password against a real session and
assert the audit_log row each one is documented (ARCHITECTURE.md, DATA_MODEL.md) to write —
previously untested despite being wired in.
"""

from collections.abc import Generator
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app import crud
from app.models import AuditLog, Profile

_FIRM_ID = uuid4()


@pytest.fixture
def session() -> Generator[Session]:
    engine = create_engine("sqlite://")
    tables = [
        Profile.__table__,  # pyright: ignore[reportAttributeAccessIssue]
        AuditLog.__table__,  # pyright: ignore[reportAttributeAccessIssue]
    ]
    SQLModel.metadata.create_all(engine, tables=tables)  # pyright: ignore[reportUnknownArgumentType]
    with Session(engine) as s:
        yield s


def _owner() -> Profile:
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


def _employee(session: Session, **overrides: object) -> Profile:
    defaults: dict[str, object] = {
        "id": uuid4(),
        "firm_id": _FIRM_ID,
        "role": "employee",
        "full_name": "Employee",
        "email": "employee@example.com",
        "is_active": True,
        "must_change_password": True,
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    employee = Profile(**defaults)  # pyright: ignore[reportArgumentType]
    session.add(employee)
    session.commit()
    session.refresh(employee)
    return employee


def _audit_rows(session: Session, action: str) -> list[AuditLog]:
    return list(session.exec(select(AuditLog).where(AuditLog.action == action)).all())


def test_create_employee_writes_audit_log(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    actor = _owner()
    new_id = uuid4()
    monkeypatch.setattr(
        crud.admin_auth,
        "create_user",
        lambda *a, **kw: SimpleNamespace(user=SimpleNamespace(id=str(new_id))),
    )

    returned_id, _ = crud.create_employee(session, actor, "New Hire", "new@example.com")

    rows = _audit_rows(session, "employee_created")
    assert len(rows) == 1
    assert rows[0].actor_id == actor.id
    assert rows[0].target_id == returned_id == new_id


def test_deactivate_employee_writes_audit_log(session: Session) -> None:
    actor = _owner()
    employee = _employee(session)

    crud.set_employee_active(session, actor, employee, is_active=False)

    rows = _audit_rows(session, "employee_deactivated")
    assert len(rows) == 1
    assert rows[0].actor_id == actor.id
    assert rows[0].target_id == employee.id


def test_reactivate_employee_writes_audit_log(session: Session) -> None:
    actor = _owner()
    employee = _employee(session, is_active=False)

    crud.set_employee_active(session, actor, employee, is_active=True)

    rows = _audit_rows(session, "employee_reactivated")
    assert len(rows) == 1
    assert rows[0].actor_id == actor.id
    assert rows[0].target_id == employee.id


def test_reset_password_writes_audit_log(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    actor = _owner()
    employee = _employee(session)
    monkeypatch.setattr(crud.admin_auth, "update_user_by_id", lambda *a, **kw: None)

    crud.reset_employee_password(session, actor, employee)
    session.commit()  # reset_employee_password itself doesn't commit — see its docstring

    rows = _audit_rows(session, "password_reset")
    assert len(rows) == 1
    assert rows[0].actor_id == actor.id
    assert rows[0].target_id == employee.id
