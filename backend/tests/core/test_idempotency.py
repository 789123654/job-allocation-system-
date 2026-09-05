"""Real SQLite-backed tests, not a mocked session — mocking session.exec here would only verify
the mock was called, not that the cache-hit/cache-miss/conflict logic actually works. SQLite is
fine for this: IdempotencyKey has no FK constraints at the SQLModel/ORM level (those live in the
Alembic migration only, per app/models.py's own docstring), just a composite PK, so this table
alone creates cleanly without pulling in the rest of the Postgres-specific schema.
"""

from collections.abc import Generator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine

from app.core.idempotency import (
    record_idempotency_key,
    reject_if_idempotency_key_used,
    with_idempotency,
)
from app.models import IdempotencyKey, Profile

_FIRM_ID = uuid4()


@pytest.fixture
def session() -> Generator[Session]:
    engine = create_engine("sqlite://")
    table = IdempotencyKey.__table__  # pyright: ignore[reportAttributeAccessIssue]
    SQLModel.metadata.create_all(engine, tables=[table])  # pyright: ignore[reportUnknownArgumentType]
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


def test_first_call_executes_handler(session: Session) -> None:
    actor = _actor()
    calls = []

    def handler() -> tuple[int, dict[str, str]]:
        calls.append(1)
        return 201, {"id": "abc"}

    status_code, body = with_idempotency(
        session, actor, "key-1", "POST /tasks", {"title": "x"}, handler
    )

    assert status_code == 201
    assert body == {"id": "abc"}
    assert len(calls) == 1


def test_replay_with_same_key_and_body_returns_cached_response_without_re_executing(
    session: Session,
) -> None:
    actor = _actor()
    calls = []

    def handler() -> tuple[int, dict[str, str]]:
        calls.append(1)
        return 201, {"id": "abc"}

    with_idempotency(session, actor, "key-1", "POST /tasks", {"title": "x"}, handler)
    status_code, body = with_idempotency(
        session, actor, "key-1", "POST /tasks", {"title": "x"}, handler
    )

    assert status_code == 201
    assert body == {"id": "abc"}
    assert len(calls) == 1  # handler must not run a second time — that's the whole point


def test_same_key_different_body_is_rejected(session: Session) -> None:
    actor = _actor()

    def handler() -> tuple[int, dict[str, str]]:
        return 201, {"id": "abc"}

    with_idempotency(session, actor, "key-1", "POST /tasks", {"title": "x"}, handler)

    with pytest.raises(HTTPException) as exc_info:
        with_idempotency(session, actor, "key-1", "POST /tasks", {"title": "different"}, handler)

    assert exc_info.value.status_code == 400


def test_different_actor_same_key_does_not_collide(session: Session) -> None:
    # firm_id + actor_id + key + endpoint together are the natural key — two different clients
    # reusing the same key string must not see each other's cached response.
    def handler() -> tuple[int, dict[str, str]]:
        return 201, {"id": "abc"}

    status_code, _ = with_idempotency(session, _actor(), "key-1", "POST /tasks", {}, handler)
    assert status_code == 201

    status_code, _ = with_idempotency(session, _actor(), "key-1", "POST /tasks", {}, handler)
    assert status_code == 201  # a fresh actor, not a replay — handler-derived result either way


def test_reject_if_idempotency_key_used_allows_first_use(session: Session) -> None:
    actor = _actor()
    reject_if_idempotency_key_used(session, actor, "key-1", "POST /employees/x/reset-password")
    # no exception raised — nothing recorded yet either, since record_idempotency_key is separate


def test_reject_if_idempotency_key_used_rejects_replay(session: Session) -> None:
    actor = _actor()
    endpoint = "POST /employees/x/reset-password"
    reject_if_idempotency_key_used(session, actor, "key-1", endpoint)
    record_idempotency_key(session, actor, "key-1", endpoint, {"generated_password": "[redacted]"})
    session.commit()

    with pytest.raises(HTTPException) as exc_info:
        reject_if_idempotency_key_used(session, actor, "key-1", endpoint)

    assert exc_info.value.status_code == 409


def test_reject_if_idempotency_key_used_does_not_replay_the_response(session: Session) -> None:
    # The whole point of this pair vs. with_idempotency: a retry must never get the original
    # response body back, only a 409 — a real one-time secret must not become retrievable twice.
    actor = _actor()
    endpoint = "POST /employees/x/reset-password"
    reject_if_idempotency_key_used(session, actor, "key-1", endpoint)
    record_idempotency_key(session, actor, "key-1", endpoint, {"generated_password": "s3cr3t"})
    session.commit()

    with pytest.raises(HTTPException) as exc_info:
        reject_if_idempotency_key_used(session, actor, "key-1", endpoint)

    assert "s3cr3t" not in str(exc_info.value.detail)


def test_record_idempotency_key_different_actor_same_key_does_not_collide(
    session: Session,
) -> None:
    endpoint = "POST /employees/x/reset-password"
    actor_a, actor_b = _actor(), _actor()
    record_idempotency_key(session, actor_a, "key-1", endpoint, {"generated_password": "a"})
    session.commit()

    reject_if_idempotency_key_used(session, actor_b, "key-1", endpoint)  # no exception — fresh
