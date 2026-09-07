"""Real Postgres concurrency test — proves `crud._lock_task`'s `SELECT ... FOR UPDATE` actually
blocks a second concurrent transaction rather than letting both racers act on the same stale
status, which is the exact TOCTOU race `Business_Logic_Security_Cheat_Sheet.md`'s "Use Database
Transactions and Locks" guards against (see `_lock_task`'s own docstring — this is the bug the
project shipped once already, found and fixed 2026-09-04). SQLite (used by every other crud test,
including `test_task_transitions.py`) silently ignores `.with_for_update()` — this property can
only be proven against real Postgres. Same real-Postgres-or-skip pattern as `test_rls_isolation.py`.
"""

import os
import threading
import time
from collections.abc import Generator
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlmodel import Session, select

from app import crud
from app.models import Task

_MIGRATIONS_URL = os.environ.get("TEST_MIGRATIONS_DATABASE_URL")
_APP_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not (_MIGRATIONS_URL and _APP_URL),
    reason="needs a real Postgres — set TEST_MIGRATIONS_DATABASE_URL/TEST_DATABASE_URL (CI does)",
)


@pytest.fixture
def assigned_task() -> Generator[dict[str, UUID]]:
    """Planted via the superuser/migration connection (bypasses RLS by construction) — same pattern
    as test_rls_isolation.py's two_firms fixture: this fixture's job is fixture data, not the
    property being tested.
    """
    assert _MIGRATIONS_URL is not None  # guaranteed by pytestmark's skipif above
    admin_engine = create_engine(_MIGRATIONS_URL)
    firm_id, owner_id, employee_id, task_id = uuid4(), uuid4(), uuid4(), uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO firms (id, name, plan, status) VALUES (:id, 'x', 'free', 'active')"),
            {"id": firm_id},
        )
        for pid, role in ((owner_id, "owner"), (employee_id, "employee")):
            conn.execute(
                text(
                    "INSERT INTO profiles (id, firm_id, role, full_name, email) "
                    "VALUES (:id, :fid, :role, 'x', :email)"
                ),
                {"id": pid, "fid": firm_id, "role": role, "email": f"{pid}@example.com"},
            )
        conn.execute(
            text(
                "INSERT INTO tasks (id, firm_id, title, assigned_to, status, created_by) "
                "VALUES (:id, :fid, 'Race me', :assignee, 'assigned', :owner)"
            ),
            {"id": task_id, "fid": firm_id, "assignee": employee_id, "owner": owner_id},
        )
    yield {"firm_id": firm_id, "task_id": task_id}
    with admin_engine.begin() as conn:
        conn.execute(text("DELETE FROM tasks WHERE firm_id = :fid"), {"fid": firm_id})
        conn.execute(text("DELETE FROM profiles WHERE firm_id = :fid"), {"fid": firm_id})
        conn.execute(text("DELETE FROM firms WHERE id = :fid"), {"fid": firm_id})
    admin_engine.dispose()


def _racer(
    engine: Engine,
    firm_id: UUID,
    task_id: UUID,
    barrier: threading.Barrier,
    outcomes: list[str],
    errors: list[BaseException],
) -> None:
    try:
        with engine.begin() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant', :fid, true)"), {"fid": str(firm_id)}
            )
            session = Session(bind=conn)
            task = session.exec(
                select(Task).where(Task.firm_id == firm_id, Task.id == task_id)
            ).one()
            barrier.wait(timeout=5)  # both racers hit crud.submit_task's FOR UPDATE at once
            try:
                crud.submit_task(session, task)
                session.flush()  # send the UPDATE now — the `with` block commits it at exit
                time.sleep(0.3)  # hold the lock long enough for the other racer to observably block
                outcomes.append("submitted")
            except crud.InvalidTaskStateError:
                outcomes.append("rejected")
    except BaseException as exc:  # surfaced in the main thread below, never swallowed
        errors.append(exc)


def test_concurrent_submit_only_one_wins(assigned_task: dict[str, UUID]) -> None:
    """Two threads race crud.submit_task against the SAME task row. Without the FOR UPDATE lock,
    both could read status='assigned' and both would "succeed" — a real double-submission. With the
    lock: whichever racer loses the race blocks until the winner commits, then re-reads the fresh
    'submitted' status and correctly raises InvalidTaskStateError. The outcome (one of each), not
    which specific thread wins, is what proves the lock — thread scheduling order isn't guaranteed.
    """
    assert _APP_URL is not None  # guaranteed by pytestmark's skipif above
    firm_id, task_id = assigned_task["firm_id"], assigned_task["task_id"]
    engine = create_engine(_APP_URL)
    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    errors: list[BaseException] = []
    threads = [
        threading.Thread(target=_racer, args=(engine, firm_id, task_id, barrier, outcomes, errors))
        for _ in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    engine.dispose()

    assert errors == []
    assert sorted(outcomes) == ["rejected", "submitted"]
