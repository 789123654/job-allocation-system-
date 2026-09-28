"""Real SQLite-backed tests, not a mocked session — mocking session.exec here would only verify
the mock was called, not that the cache-hit/cache-miss/conflict logic actually works. SQLite is
fine for this: IdempotencyKey has no FK constraints at the SQLModel/ORM level (those live in the
Alembic migration only, per app/models.py's own docstring), just a composite PK, so this table
alone creates cleanly without pulling in the rest of the Postgres-specific schema.
"""

from collections.abc import Generator
from datetime import UTC, datetime
from uuid import UUID, uuid4

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


def _actor(firm_id: UUID = _FIRM_ID) -> Profile:
    return Profile(
        id=uuid4(),
        firm_id=firm_id,
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


def test_record_idempotency_key_different_firm_same_key_does_not_collide(
    session: Session,
) -> None:
    """ASVS 5 8.4.1 / Multi_Tenant_Security_Cheat_Sheet.md ("prefix all cache keys with tenant
    identifier" — the same principle applied to this row's composite key, not a cache key).

    Ordinary test, not blind: production is already protected by the idempotency_keys table's own
    RLS policy (`CREATE POLICY tenant_isolation ON idempotency_keys USING (firm_id =
    current_setting('app.current_tenant', true)::uuid)`, alembic/versions/dd9b07e031bf), verified
    generically for RLS-in-general by tests/crud/test_rls_isolation.py — this is defense-in-depth
    on top of an already-verified boundary, the same shape as code-review findings #16/#18/#19.

    Real gap this closes: every existing test in this file (including the "different actor" one
    right above) uses the single module-level `_FIRM_ID` for every `_actor()` call — none ever
    exercised a genuinely different firm_id, so a mutation to either function's own `firm_id ==`
    comparison (crud-review 2026-09-15 mutation sweep: 10 survived mutants on
    reject_if_idempotency_key_used, 4 on record_idempotency_key) had nothing in this SQLite-only
    unit suite to catch it — RLS wouldn't exist to compensate here either, since SQLite has no RLS
    at all.

    First attempt at this test used two DIFFERENT actor ids across the two firms — that accidentally
    passed even with `firm_id` dropped from the WHERE clause entirely, since `actor_id` alone still
    disambiguated the rows, giving a false sense of coverage. The real adversarial case, verified
    against `Profile`'s own composite primary key (`id` + `firm_id`, app/models.py:28-29 — the
    schema has no constraint stopping the same `id` from having a profile row in a second firm,
    e.g. one person who owns one firm and is also staff at another), is the SAME actor id used
    across two different firms — only then does firm_id do any disambiguating work at all.
    """
    endpoint = "POST /employees/x/reset-password"
    other_firm_id = uuid4()
    assert other_firm_id != _FIRM_ID
    shared_actor_id = uuid4()
    actor_firm_a = _actor()
    actor_firm_a.id = shared_actor_id
    actor_firm_b = _actor(firm_id=other_firm_id)
    actor_firm_b.id = shared_actor_id  # same person, second firm — actually tests firm_id

    record_idempotency_key(session, actor_firm_a, "key-1", endpoint, {"generated_password": "a"})
    session.commit()

    # Firm A's use of "key-1" must not block this same person's own first use of the identical key
    # text while acting for Firm B.
    reject_if_idempotency_key_used(session, actor_firm_b, "key-1", endpoint)  # no exception

    # And the reverse: Firm B recording its own use must not let Firm A's *original* usage look
    # like it was ever consumed by anyone else — re-confirm Firm A's own key is still (correctly)
    # rejected as already-used, not silently freed up by Firm B's unrelated insert.
    with pytest.raises(HTTPException) as exc_info:
        reject_if_idempotency_key_used(session, actor_firm_a, "key-1", endpoint)
    assert exc_info.value.status_code == 409


def test_expired_idempotency_key_treats_request_as_new(session: Session) -> None:
    """Code-review finding #13 (2026-09-14) — adapted from WSTG-BUSL-04 (Process Timing: "whether
    transactions can be completed after an intended timeout window"), the closest WSTG procedure
    found via a whole-directory keyword sweep (idempotent/replay/race/duplicate/TOCTOU) — no exact
    match exists for idempotency-key TTL reuse specifically.

    A key reused after the 24h TTL must be treated as genuinely new: the handler must actually run,
    the real fresh result must be returned, and the stored row must reflect it — never the stale
    row's data, which is exactly what the pre-fix code silently returned instead.
    """
    from sqlmodel import select

    from app.core.db import as_aware_utc

    actor = _actor()

    # Seed an already-expired row directly — this key's PK slot is occupied by a >24h-old result,
    # simulating "reused after TTL" without needing to mock time (with_idempotency itself computes
    # `cutoff` from the real current time, so patching `datetime.now` would have to fake the exact
    # same module-global object — a stale row via direct insert avoids that entirely).
    stale_created_at = datetime(2020, 1, 1, tzinfo=UTC)  # far past any real 24h cutoff
    session.add(
        IdempotencyKey(
            firm_id=actor.firm_id,
            actor_id=actor.id,
            idempotency_key="key-1",
            endpoint="POST /tasks",
            request_hash="stale-hash",
            response_status=201,
            response_body={"id": "stale-response"},
            created_at=stale_created_at,
        )
    )
    session.commit()

    calls = 0

    def handler() -> tuple[int, dict[str, str]]:
        nonlocal calls
        calls += 1
        return 201, {"id": "fresh-response"}

    status_code, body = with_idempotency(
        session, actor, "key-1", "POST /tasks", {"title": "x"}, handler
    )

    # (a) the handler actually ran — TTL expiry means this is a new request, not a replay
    assert calls == 1, "handler must be called for a key reused after its TTL expired"
    # (b) the fresh result is what's returned, never the stale seeded one
    assert status_code == 201
    assert body == {"id": "fresh-response"}

    # (c) the stored row now reflects the new result, not the stale one
    updated_row = session.exec(
        select(IdempotencyKey).where(
            (IdempotencyKey.firm_id == actor.firm_id)
            & (IdempotencyKey.actor_id == actor.id)
            & (IdempotencyKey.idempotency_key == "key-1")
            & (IdempotencyKey.endpoint == "POST /tasks")
        )
    ).first()
    assert updated_row is not None
    assert updated_row.response_body == {"id": "fresh-response"}
    assert as_aware_utc(updated_row.created_at) > stale_created_at
