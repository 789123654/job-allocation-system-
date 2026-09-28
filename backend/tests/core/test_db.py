"""Structural tripwire, not a behavior test — see core/db.py's `commit_or_recover` docstring for
the history this guards. That helper exists because the same commit/rollback-recovery shape was
independently hand-rolled at two call sites, and the fix (re-`set_config` after a conflict
rollback) only made it into the first one (SECURITY_AUDIT_CHECKLIST.md, 2026-09-09 follow-up).

Every `session.rollback()` in backend/app/ is enumerated below. The count is meant to change only
on a deliberate decision — route the new one through `commit_or_recover`, or add it here with a
one-line reason the same way the existing entries do — never by accident. A plain code review can
miss a hand-rolled rollback the same way it missed the original bug (the tutorial-shaped code
looks correct in isolation); this test doesn't rely on a reviewer noticing.
"""

import contextlib
import socket
import threading
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

from app.core import db
from app.core.config import settings

_APP_DIR = Path(__file__).resolve().parents[2] / "app"

# path relative to backend/app/ -> expected count of literal `session.rollback()` calls.
_EXPECTED_ROLLBACK_SITES = {
    # The one place this pattern is allowed to be written from scratch.
    "core/db.py": 1,
    # Both below: raise immediately after rollback, no further session read or query — so neither
    # is exposed to the expired-attribute bug commit_or_recover exists to prevent, and neither
    # gains anything from routing through it. (reset-password's former hand-rolled rollback here
    # is gone — that site now goes through commit_or_recover, 2026-09-14 code review fix.)
    "crud.py": 2,  # create_job_type (raises DuplicateJobTypeNameError) +
    # create_employee's compensating-delete path (rolls back, best-effort deletes the now-orphaned
    # Supabase Auth user, then re-raises — 2026-09-14 code review fix)
}


def test_every_rollback_site_is_accounted_for() -> None:
    counts = {
        str(path.relative_to(_APP_DIR).as_posix()): path.read_text(encoding="utf-8").count(
            "session.rollback()"
        )
        for path in _APP_DIR.rglob("*.py")
    }
    actual = {path: count for path, count in counts.items() if count > 0}
    assert actual == _EXPECTED_ROLLBACK_SITES, (
        "A session.rollback() site was added, removed, or moved. If added: does anything read an "
        "ORM attribute or run another query on the session afterward? If yes, route it through "
        "core.db.commit_or_recover instead of hand-rolling commit/except-IntegrityError/rollback — "
        "that's exactly how this bug shipped twice. If no (it raises or returns immediately), add "
        "it to _EXPECTED_ROLLBACK_SITES above with a one-line reason, same as the existing entries."
    )


def test_connect_args_wires_the_configured_connect_timeout() -> None:
    """The plumbing half of the fix: `db.engine` itself can't be introspected for connect_args
    after construction (SQLAlchemy doesn't expose it — it's merged into a pool-internal closure),
    so this pins the pure function `engine = create_engine(...)` actually calls."""
    assert db._connect_args() == {  # pyright: ignore[reportPrivateUsage]
        "connect_timeout": settings.DB_CONNECT_TIMEOUT_SECONDS
    }


def test_a_new_physical_connection_attempt_is_bounded_not_indefinite() -> None:
    """The real symptom this closes (SECURITY_AUDIT_CHECKLIST.md): opening a fresh Postgres
    connection with no connect_timeout has no application-level bound at all -- confirmed live
    (2026-09-22) via a faulthandler thread-stack dump during a schemathesis fuzz run:
    get_current_profile (api/deps.py) sat inside psycopg.connection.connect -> selectors.select,
    blocked for the full ~260s Windows took to give up the TCP handshake on its own.

    A local listener that accepts the TCP connection but never answers Postgres's startup packet
    reproduces that exact "connect() looks fine, then nothing happens" shape deterministically --
    unlike pointing at an unreachable IP, which can fail fast for reasons unrelated to
    connect_timeout and wouldn't actually exercise it.
    """
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    def accept_and_stall() -> None:
        with contextlib.suppress(OSError):
            listener.accept()  # accepted, but never sends a reply -- the stall.

    thread = threading.Thread(target=accept_and_stall, daemon=True)
    thread.start()
    engine = create_engine(
        f"postgresql+psycopg://u:p@127.0.0.1:{port}/db", connect_args={"connect_timeout": 1}
    )
    try:
        started = time.monotonic()
        with pytest.raises(OperationalError):
            engine.connect()
        elapsed = time.monotonic() - started
        # Generous bound above the 1s connect_timeout -- not asserting exact timing, only that
        # it's bounded at all (the pre-fix code had no bound whatsoever).
        assert elapsed < 5.0
    finally:
        engine.dispose()
        listener.close()
        thread.join(timeout=1)
