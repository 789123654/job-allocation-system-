"""Real Postgres concurrency tests — prove `crud._lock_task`/`_lock_issue`'s `SELECT ... FOR
UPDATE` actually blocks a second concurrent transaction AND that the blocked transaction sees the
*fresh* post-lock row, not a stale one already cached in its session's identity map. This second
property is the one that was actually broken: `.with_for_update()` alone takes the real database
lock, but without `.execution_options(populate_existing=True)`, SQLAlchemy silently hands back
whatever Python object was already loaded for that primary key — found 2026-09-07 when this test
(then only `test_concurrent_submit_only_one_wins`) failed against real Postgres in CI (PR #8) with
both racers reporting "submitted" instead of one "rejected". See `_lock_task`'s docstring and
`SECURITY_AUDIT_CHECKLIST.md` for the full writeup. SQLite (used by every other crud test,
including `test_task_transitions.py`) silently ignores `.with_for_update()` entirely and can't
reproduce either property — this can only be proven against real Postgres. Same
real-Postgres-or-skip pattern as `test_rls_isolation.py`.

`reset_employee_password`'s inline lock has the identical code shape (unlocked read in the route,
then `.with_for_update()` in this function, in the same session) but, unlike `submit_task`/
`resolve_issue`, nothing downstream reads the locked object's *old* field values to decide
whether to proceed — every write here is unconditional. So the identity-map bug has no currently
observable effect on this call site: `test_concurrent_reset_password_serializes` below proves the
lock still blocks correctly (a regression guard, and cheap insurance against a future change that
adds a conditional read), not a reproduction of a live bug the way the other two tests are.
"""

import os
import threading
import time
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlmodel import Session, select

from app import crud
from app.models import Issue, Profile, Task

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
        # notifications must go first: submit_task's _notify_owners inserts rows that FK to this
        # task, and tasks' own delete fails with ForeignKeyViolation otherwise (fixture's own bug,
        # separate from the crud.py finding — found the same day, fixed here).
        conn.execute(text("DELETE FROM notifications WHERE firm_id = :fid"), {"fid": firm_id})
        conn.execute(text("DELETE FROM tasks WHERE firm_id = :fid"), {"fid": firm_id})
        conn.execute(text("DELETE FROM profiles WHERE firm_id = :fid"), {"fid": firm_id})
        conn.execute(text("DELETE FROM firms WHERE id = :fid"), {"fid": firm_id})
    admin_engine.dispose()


@pytest.fixture
def open_issue() -> Generator[dict[str, UUID]]:
    """Same planting pattern as `assigned_task` — a task plus one open `Issue` raised against it."""
    assert _MIGRATIONS_URL is not None  # guaranteed by pytestmark's skipif above
    admin_engine = create_engine(_MIGRATIONS_URL)
    firm_id, owner_id, employee_id, task_id, issue_id = uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
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
        conn.execute(
            text(
                "INSERT INTO issues (id, firm_id, task_id, raised_by, description, status) "
                "VALUES (:id, :fid, :task_id, :raised_by, 'Race me too', 'open')"
            ),
            {"id": issue_id, "fid": firm_id, "task_id": task_id, "raised_by": employee_id},
        )
    yield {"firm_id": firm_id, "task_id": task_id, "issue_id": issue_id, "owner_id": owner_id}
    with admin_engine.begin() as conn:
        # notifications first: resolve_issue now writes an `issue_resolved` notification that
        # references the issue (notifications_firm_id_issue_id_fkey), so deleting issues first
        # violates that FK — found when the real-Postgres suite was first run locally.
        conn.execute(text("DELETE FROM notifications WHERE firm_id = :fid"), {"fid": firm_id})
        conn.execute(text("DELETE FROM issues WHERE firm_id = :fid"), {"fid": firm_id})
        conn.execute(text("DELETE FROM tasks WHERE firm_id = :fid"), {"fid": firm_id})
        conn.execute(text("DELETE FROM profiles WHERE firm_id = :fid"), {"fid": firm_id})
        conn.execute(text("DELETE FROM firms WHERE id = :fid"), {"fid": firm_id})
    admin_engine.dispose()


@pytest.fixture
def firm_employee() -> Generator[dict[str, UUID]]:
    """A bare firm/owner/employee triple — for `reset_employee_password`, which touches no task
    or issue at all.
    """
    assert _MIGRATIONS_URL is not None  # guaranteed by pytestmark's skipif above
    admin_engine = create_engine(_MIGRATIONS_URL)
    firm_id, owner_id, employee_id = uuid4(), uuid4(), uuid4()
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
    yield {"firm_id": firm_id, "owner_id": owner_id, "employee_id": employee_id}
    with admin_engine.begin() as conn:
        conn.execute(text("DELETE FROM audit_log WHERE firm_id = :fid"), {"fid": firm_id})
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


def _issue_racer(
    engine: Engine,
    firm_id: UUID,
    issue_id: UUID,
    owner_id: UUID,
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
            issue = session.exec(
                select(Issue).where(Issue.firm_id == firm_id, Issue.id == issue_id)
            ).one()
            actor = session.exec(
                select(Profile).where(Profile.firm_id == firm_id, Profile.id == owner_id)
            ).one()
            barrier.wait(timeout=5)  # both racers hit crud.resolve_issue's FOR UPDATE at once
            try:
                crud.resolve_issue(session, actor, issue, "clarified", "notes", None, None, None)
                session.flush()
                time.sleep(0.3)  # hold the lock long enough for the other racer to observably block
                outcomes.append("resolved")
            except crud.InvalidIssueStateError:
                outcomes.append("rejected")
    except BaseException as exc:  # surfaced in the main thread below, never swallowed
        errors.append(exc)


def test_concurrent_resolve_issue_only_one_wins(open_issue: dict[str, UUID]) -> None:
    """Same shape as test_concurrent_submit_only_one_wins, for `_lock_issue`/`resolve_issue`:
    `resolve_issue` reads `locked.status != "open"` to decide whether to raise
    InvalidIssueStateError — the exact "read an old cached value after the lock" shape the
    identity-map bug breaks. Proves `_lock_issue`'s `populate_existing=True` fix independently of
    `_lock_task`'s.
    """
    firm_id, issue_id = open_issue["firm_id"], open_issue["issue_id"]
    owner_id = open_issue["owner_id"]
    engine = create_engine(_APP_URL)  # type: ignore[arg-type]  # guaranteed by pytestmark
    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    errors: list[BaseException] = []
    threads = [
        threading.Thread(
            target=_issue_racer,
            args=(engine, firm_id, issue_id, owner_id, barrier, outcomes, errors),
        )
        for _ in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    engine.dispose()

    assert errors == []
    assert sorted(outcomes) == ["rejected", "resolved"]


def _reset_password_racer(
    engine: Engine,
    firm_id: UUID,
    owner_id: UUID,
    employee_id: UUID,
    barrier: threading.Barrier,
    completed_at: list[float],
    errors: list[BaseException],
) -> None:
    try:
        with engine.begin() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant', :fid, true)"), {"fid": str(firm_id)}
            )
            session = Session(bind=conn)
            employee = session.exec(
                select(Profile).where(Profile.firm_id == firm_id, Profile.id == employee_id)
            ).one()
            actor = session.exec(
                select(Profile).where(Profile.firm_id == firm_id, Profile.id == owner_id)
            ).one()
            barrier.wait(timeout=5)
            crud.reset_employee_password(session, actor, employee)
            session.flush()
            time.sleep(0.3)  # hold the lock long enough for the other racer to observably block
            completed_at.append(time.monotonic())
    except BaseException as exc:  # surfaced in the main thread below, never swallowed
        errors.append(exc)


def test_concurrent_reset_password_serializes(
    firm_employee: dict[str, UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`reset_employee_password` has no state check for the identity-map bug to break (see module
    docstring) — this proves the row lock still serializes two concurrent resets rather than
    letting them interleave, as a regression guard: both racers must complete (no exception), and
    since each holds the lock for 0.3s, the two completion timestamps must be at least that far
    apart, meaning the second racer genuinely blocked on the first rather than running in parallel.
    """
    monkeypatch.setattr(crud.admin_auth, "update_user_by_id", lambda *a, **kw: None)
    firm_id = firm_employee["firm_id"]
    owner_id, employee_id = firm_employee["owner_id"], firm_employee["employee_id"]
    engine = create_engine(_APP_URL)  # type: ignore[arg-type]  # guaranteed by pytestmark
    barrier = threading.Barrier(2)
    completed_at: list[float] = []
    errors: list[BaseException] = []
    threads = [
        threading.Thread(
            target=_reset_password_racer,
            args=(engine, firm_id, owner_id, employee_id, barrier, completed_at, errors),
        )
        for _ in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    engine.dispose()

    assert errors == []
    assert len(completed_at) == 2
    assert abs(completed_at[0] - completed_at[1]) >= 0.25  # allows a little scheduling slack


@pytest.fixture
def overdue_task() -> Generator[dict[str, UUID]]:
    """A task deadline safely in the past, assigned to `employee_id` and still 'assigned' (an
    active status) — the exact shape `_ensure_employee_deadline_notifications` turns into a
    `task_overdue_own` notification. Same planting pattern as `assigned_task`.
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
                "INSERT INTO tasks (id, firm_id, title, assigned_to, status, created_by, deadline) "
                "VALUES (:id, :fid, 'Race me', :assignee, 'assigned', :owner, :deadline)"
            ),
            {
                "id": task_id,
                "fid": firm_id,
                "assignee": employee_id,
                "owner": owner_id,
                "deadline": datetime.now(UTC) - timedelta(days=2),
            },
        )
    yield {"firm_id": firm_id, "task_id": task_id, "employee_id": employee_id}
    with admin_engine.begin() as conn:
        conn.execute(text("DELETE FROM notifications WHERE firm_id = :fid"), {"fid": firm_id})
        conn.execute(text("DELETE FROM tasks WHERE firm_id = :fid"), {"fid": firm_id})
        conn.execute(text("DELETE FROM profiles WHERE firm_id = :fid"), {"fid": firm_id})
        conn.execute(text("DELETE FROM firms WHERE id = :fid"), {"fid": firm_id})
    admin_engine.dispose()


def _notification_racer(
    engine: Engine,
    firm_id: UUID,
    employee_id: UUID,
    barrier: threading.Barrier,
    errors: list[BaseException],
) -> None:
    try:
        # Bound directly to the engine, not a pre-opened connection like the racers above — this
        # mirrors get_session()'s real Session(engine, expire_on_commit=False) exactly, because
        # _ensure_deadline_notifications manages its own transaction boundaries internally
        # (commit()/rollback(), then a fresh set_config()) the same way a real request does across
        # get_current_profile's set_config and this function's own mid-request commit.
        with Session(engine, expire_on_commit=False) as session:
            session.execute(  # pyright: ignore[reportDeprecated] — same as get_current_profile's call
                text("SELECT set_config('app.current_tenant', :fid, true)"), {"fid": str(firm_id)}
            )
            actor = session.exec(
                select(Profile).where(Profile.firm_id == firm_id, Profile.id == employee_id)
            ).one()
            barrier.wait(timeout=5)  # both racers hit the missing-notification SELECT at once
            # Through the real public entry point (same call `GET /notifications` makes), not the
            # private `_ensure_deadline_notifications` directly — exercises the exact production
            # path and avoids reaching past the module boundary for something with a public route.
            crud.list_notifications(session, actor, 0, 50, False)
    except BaseException as exc:  # surfaced in the main thread below, never swallowed
        errors.append(exc)


def test_concurrent_deadline_poll_dedups_correctly(overdue_task: dict[str, UUID]) -> None:
    """Two threads race `list_notifications` (and its internal `_ensure_deadline_notifications`
    step) against the same overdue task/recipient — the real shape of two near-simultaneous
    `GET /notifications` polls (ARCHITECTURE.md §8's 30-60s polling interval). Without
    `ix_notifications_dedup`'s partial UNIQUE index, both threads
    could observe the notification "missing" and both insert it — two rows for the same
    (recipient, type, task). With the index: whichever thread's commit lands second hits a real
    IntegrityError, which `_ensure_deadline_notifications` must catch and roll back from, not let
    propagate. This is the real-Postgres proof for that catch, per this file's own established
    standard (module docstring) — reasoning about the race alone was never enough on its own.
    """
    assert _APP_URL is not None  # guaranteed by pytestmark's skipif above
    firm_id, task_id = overdue_task["firm_id"], overdue_task["task_id"]
    employee_id = overdue_task["employee_id"]
    engine = create_engine(_APP_URL)
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []
    threads = [
        threading.Thread(
            target=_notification_racer, args=(engine, firm_id, employee_id, barrier, errors)
        )
        for _ in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    engine.dispose()

    assert _MIGRATIONS_URL is not None  # guaranteed by pytestmark's skipif above
    admin_engine = create_engine(_MIGRATIONS_URL)
    with admin_engine.begin() as conn:
        count = conn.execute(
            text(
                "SELECT count(*) FROM notifications WHERE firm_id = :fid AND recipient_id = :rid "
                "AND type = 'task_overdue_own' AND task_id = :tid"
            ),
            {"fid": firm_id, "rid": employee_id, "tid": task_id},
        ).scalar_one()
    admin_engine.dispose()

    assert errors == []  # the IntegrityError catch must have absorbed the loser's race, not raised
    assert count == 1  # exactly one notification — no duplicate, and none lost
