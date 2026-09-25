"""Blind test (written from the behavior spec only, without reading crud.create_employee's body)
for its compensating-cleanup behavior: if the Supabase Auth user gets created but the subsequent
local DB commit fails, create_employee must best-effort delete that just-created Supabase Auth
user (so the email isn't silently consumed forever by an orphaned account with no local
employee row) and then still let the original error propagate. Same real-SQLite-session pattern
as tests/crud/test_employee_audit_log.py.
"""

from collections.abc import Generator
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlmodel import Session, SQLModel, create_engine

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


def test_create_employee_deletes_auth_user_when_local_commit_fails(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """create_user succeeds, then the local commit fails for some reason (mocked here as a bare
    session.commit() failure) — the just-created Supabase Auth user must be deleted, and the
    original error must still propagate (the request must still fail).
    """
    actor = _owner()
    new_id = uuid4()
    monkeypatch.setattr(
        crud.admin_auth,
        "create_user",
        lambda *a, **kw: SimpleNamespace(user=SimpleNamespace(id=str(new_id))),
    )
    delete_user_mock = MagicMock()
    monkeypatch.setattr(crud.admin_auth, "delete_user", delete_user_mock)

    def _fail_commit() -> None:
        raise RuntimeError("boom-commit-xyz")

    monkeypatch.setattr(session, "commit", _fail_commit)

    with pytest.raises(Exception) as exc_info:
        crud.create_employee(session, actor, "Jane Doe", "jane@example.com")

    # (1) the original error propagates — not swallowed, not turned into a fake success.
    assert "boom-commit-xyz" in str(exc_info.value)

    # (2) delete_user was called with the just-created user's id (positional or keyword).
    delete_user_mock.assert_called_once()
    call = delete_user_mock.call_args
    called_id = call.args[0] if call.args else call.kwargs.get("id") or call.kwargs.get("user_id")
    assert called_id == str(new_id)


def test_create_employee_original_error_propagates_even_if_cleanup_also_fails(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cleanup delete_user call itself also fails (e.g. Supabase is down too) — this must not
    change the outcome: the ORIGINAL commit failure must still be what propagates, not the
    cleanup's own error, and definitely not a silent success.
    """
    actor = _owner()
    new_id = uuid4()
    monkeypatch.setattr(
        crud.admin_auth,
        "create_user",
        lambda *a, **kw: SimpleNamespace(user=SimpleNamespace(id=str(new_id))),
    )
    monkeypatch.setattr(
        crud.admin_auth, "delete_user", MagicMock(side_effect=RuntimeError("boom-delete-xyz"))
    )

    def _fail_commit() -> None:
        raise RuntimeError("boom-commit-xyz")

    monkeypatch.setattr(session, "commit", _fail_commit)

    with pytest.raises(Exception) as exc_info:
        crud.create_employee(session, actor, "Jane Doe", "jane@example.com")

    assert "boom-commit-xyz" in str(exc_info.value)
    assert "boom-delete-xyz" not in str(exc_info.value)
