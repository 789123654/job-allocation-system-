"""Real Postgres concurrency test for `with_idempotency`'s post-rollback recovery path — same
threading.Barrier(2)-against-real-Postgres standard as tests/crud/test_concurrency.py's own module
docstring establishes, applied here for the first time. `test_idempotency.py` (this directory)
covers the cache-hit/cache-miss/conflict logic against real SQLite, but a genuine two-thread race
on the same Idempotency-Key can only be produced against real Postgres, and only that race exercises
`with_idempotency`'s `except IntegrityError` branch at all — SQLite never raises it here since
nothing in that suite fires two concurrent commits at the same composite primary key.

Found 2026-09-09 (docs/SECURITY_AUDIT_CHECKLIST.md's original tenant-context finding, 2026-09-08,
was the first instance of this mechanism; crud.py's `_ensure_deadline_notifications` was the
second, tests/crud/test_concurrency.py's own test_concurrent_deadline_poll_dedups_correctly): on the
race's losing thread, `session.rollback()` expired `actor`, and the winner-lookup query that follows
read `actor.firm_id`/`actor.id` — an expired attribute read SQLAlchemy silently turns into a lazy-
refresh SELECT with no tenant context yet, crashing with `invalid input syntax for type uuid: ""`.
Worse than the notification case: this function had no re-`set_config()` at all, so even past the
actor-refresh crash, the winner-lookup SELECT itself had no tenant context either (idempotency_keys
has RLS too — dd9b07e031bf's `tenant_isolation` policy).
"""

import os
import threading
from collections.abc import Generator
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlmodel import Session, select

from app.core.idempotency import with_idempotency
from app.models import Profile

_MIGRATIONS_URL = os.environ.get("TEST_MIGRATIONS_DATABASE_URL")
_APP_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not (_MIGRATIONS_URL and _APP_URL),
    reason="needs a real Postgres — set TEST_MIGRATIONS_DATABASE_URL/TEST_DATABASE_URL (CI does)",
)


@pytest.fixture
def firm_profile() -> Generator[dict[str, UUID]]:
    """A bare firm/owner pair — `with_idempotency` only ever reads `actor.firm_id`/`actor.id`, no
    task or issue needed. Same planting pattern as test_concurrency.py's firm_employee fixture.
    """
    assert _MIGRATIONS_URL is not None  # guaranteed by pytestmark's skipif above
    admin_engine = create_engine(_MIGRATIONS_URL)
    firm_id, profile_id = uuid4(), uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO firms (id, name, plan, status) VALUES (:id, 'x', 'free', 'active')"),
            {"id": firm_id},
        )
        conn.execute(
            text(
                "INSERT INTO profiles (id, firm_id, role, full_name, email) "
                "VALUES (:id, :fid, 'owner', 'x', :email)"
            ),
            {"id": profile_id, "fid": firm_id, "email": f"{profile_id}@example.com"},
        )
    yield {"firm_id": firm_id, "profile_id": profile_id}
    with admin_engine.begin() as conn:
        conn.execute(text("DELETE FROM idempotency_keys WHERE firm_id = :fid"), {"fid": firm_id})
        conn.execute(text("DELETE FROM profiles WHERE firm_id = :fid"), {"fid": firm_id})
        conn.execute(text("DELETE FROM firms WHERE id = :fid"), {"fid": firm_id})
    admin_engine.dispose()


def _idempotency_racer(
    engine: Engine,
    firm_id: UUID,
    profile_id: UUID,
    call_id: str,
    barrier: threading.Barrier,
    results: list[tuple[int, dict[str, Any]]],
    errors: list[BaseException],
) -> None:
    try:
        # Bound directly to the engine, matching get_session()'s real shape — with_idempotency
        # manages its own commit()/rollback() internally, same reasoning as
        # test_concurrency.py's _notification_racer.
        with Session(engine, expire_on_commit=False) as session:
            session.execute(  # pyright: ignore[reportDeprecated] — same as get_current_profile's call
                text("SELECT set_config('app.current_tenant', :fid, true)"), {"fid": str(firm_id)}
            )
            actor = session.exec(
                select(Profile).where(Profile.firm_id == firm_id, Profile.id == profile_id)
            ).one()

            def handler() -> tuple[int, dict[str, Any]]:
                # A per-thread-unique body — proves which thread's response actually won: if the
                # loser recovered a *different* call_id than its own, that's the real winner's
                # cached row, not its own independently-computed result.
                return 201, {"call_id": call_id}

            barrier.wait(timeout=5)  # both racers hit the same-key commit race at once
            result = with_idempotency(
                session, actor, "race-key", "POST /tasks", {"title": "x"}, handler
            )
            results.append(result)
    except BaseException as exc:  # surfaced in the main thread below, never swallowed
        errors.append(exc)


def test_concurrent_identical_retry_recovers_the_winner(firm_profile: dict[str, UUID]) -> None:
    """Two threads call `with_idempotency` with the exact same Idempotency-Key/endpoint/actor at
    the same instant — the real shape of a genuinely concurrent retry (a client double-firing a
    request, or a proxy retrying alongside the original still in flight). Without the fix: the
    losing thread's post-rollback winner lookup crashes on an expired-attribute refresh with no
    tenant context. With the fix: both threads return, and both return the *same* response — the
    loser recovered the winner's actual committed row rather than crashing or silently returning
    its own separately-computed (and un-cached) body.
    """
    assert _APP_URL is not None  # guaranteed by pytestmark's skipif above
    firm_id, profile_id = firm_profile["firm_id"], firm_profile["profile_id"]
    engine = create_engine(_APP_URL)
    barrier = threading.Barrier(2)
    results: list[tuple[int, dict[str, Any]]] = []
    errors: list[BaseException] = []
    threads = [
        threading.Thread(
            target=_idempotency_racer,
            args=(engine, firm_id, profile_id, f"racer-{i}", barrier, results, errors),
        )
        for i in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    engine.dispose()

    assert errors == []
    assert len(results) == 2
    assert results[0] == results[1]  # both recovered the same winning response
    assert results[0][1]["call_id"] in ("racer-0", "racer-1")  # a real call won, not a third value
