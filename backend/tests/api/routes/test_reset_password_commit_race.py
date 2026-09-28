"""Blind test (written from the behavior spec only, without reading employees.py's reset_password
route handler or crud.reset_employee_password's body) for reset-password's commit-failure
handling.

Uses a real, FILE-based SQLite DB (not the `sqlite://` in-memory URL other tests here use) so that
two independent `Session` objects backed by two independent connections can genuinely see each
other's committed writes without SQLAlchemy's SQLite single-connection pooling quirks getting in
the way. That's needed to reproduce the actual race window the spec describes: a concurrent
identical request's IdempotencyKey row must land strictly AFTER this request's own
`reject_if_idempotency_key_used` check (or that check would just 409 immediately, per
test_reset_password_replay_is_409_and_never_returns_password in test_employees.py) but BEFORE —
or exactly at — this request's own commit.
"""

from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine

from app import crud
from app.api import deps
from app.main import app
from app.models import AuditLog, IdempotencyKey, Profile

_FIRM_ID = uuid4()


@pytest.fixture
def engine(tmp_path: Path) -> Generator[Engine]:
    eng = create_engine(f"sqlite:///{tmp_path / 'reset_password_race.db'}")
    tables = [
        Profile.__table__,  # pyright: ignore[reportAttributeAccessIssue]
        AuditLog.__table__,  # pyright: ignore[reportAttributeAccessIssue]
        IdempotencyKey.__table__,  # pyright: ignore[reportAttributeAccessIssue]
    ]
    SQLModel.metadata.create_all(eng, tables=tables)  # pyright: ignore[reportUnknownArgumentType]
    yield eng
    eng.dispose()


@pytest.fixture
def request_session(engine: Engine) -> Generator[Session]:
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


def _employee(session: Session) -> Profile:
    employee = Profile(
        id=uuid4(),
        firm_id=_FIRM_ID,
        role="employee",
        full_name="Employee",
        email="employee@example.com",
        is_active=True,
        must_change_password=True,
        created_at=datetime.now(UTC),
    )
    session.add(employee)
    session.commit()
    session.refresh(employee)
    return employee


@pytest.fixture
def client(request_session: Session, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient]:
    monkeypatch.setattr(crud.admin_auth, "update_user_by_id", lambda *a, **kw: None)
    app.dependency_overrides[deps.get_session] = lambda: request_session
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_reset_password_tolerates_genuine_concurrent_idempotency_key_race(
    engine: Engine,
    request_session: Session,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second, near-simultaneous request using the exact same Idempotency-Key commits its own
    matching IdempotencyKey row (same firm_id/actor_id/idempotency_key/endpoint) on a fully
    separate connection, landing exactly when THIS request's own commit fires — a real UNIQUE/PK
    violation on the real commit below, not a mocked exception. This must still be tolerated: 200
    with a generated password, not an error.
    """
    actor = _owner()
    request_session.add(actor)
    request_session.commit()
    request_session.refresh(actor)
    app.dependency_overrides[deps.require_owner] = lambda: actor

    employee = _employee(request_session)
    idempotency_key = str(uuid4())
    endpoint = f"POST /employees/{employee.id}/reset-password"

    real_commit = request_session.commit

    def _commit_after_concurrent_winner() -> None:
        winner_session = Session(engine)
        winner_session.add(
            IdempotencyKey(
                firm_id=actor.firm_id,
                actor_id=actor.id,
                idempotency_key=idempotency_key,
                endpoint=endpoint,
                request_hash="",
                response_status=200,
                response_body={"generated_password": "concurrent-winner-pw"},
                created_at=datetime.now(UTC),
            )
        )
        winner_session.commit()
        winner_session.close()
        real_commit()  # now genuinely raises IntegrityError — same PK already committed above

    monkeypatch.setattr(request_session, "commit", _commit_after_concurrent_winner)

    response = client.post(
        f"/employees/{employee.id}/reset-password",
        headers={"Idempotency-Key": idempotency_key},
    )

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body.get("generated_password"), str)
    assert body["generated_password"]


def test_reset_password_500s_when_commit_fails_for_a_different_reason(
    request_session: Session, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Commit fails, but NOT because a genuine matching IdempotencyKey row exists (none does) — the
    password really was rotated on Supabase's side (update_user_by_id is mocked, but the route
    doesn't know that), yet nothing could be recorded locally. Must be a 500, never a 200 with a
    password pretending the reset fully succeeded.
    """
    actor = _owner()
    request_session.add(actor)
    request_session.commit()
    request_session.refresh(actor)
    app.dependency_overrides[deps.require_owner] = lambda: actor

    employee = _employee(request_session)
    idempotency_key = str(uuid4())

    def _fail_commit() -> None:
        raise IntegrityError("forced failure — no real conflicting row", {}, Exception("forced"))

    monkeypatch.setattr(request_session, "commit", _fail_commit)

    response = client.post(
        f"/employees/{employee.id}/reset-password",
        headers={"Idempotency-Key": idempotency_key},
    )

    assert response.status_code == 500
    assert "generated_password" not in response.text
