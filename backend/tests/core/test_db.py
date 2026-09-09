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

from pathlib import Path

_APP_DIR = Path(__file__).resolve().parents[2] / "app"

# path relative to backend/app/ -> expected count of literal `session.rollback()` calls.
_EXPECTED_ROLLBACK_SITES = {
    # The one place this pattern is allowed to be written from scratch.
    "core/db.py": 1,
    # Both below: raise/return immediately after rollback, no further session read or query — so
    # neither one is exposed to the expired-attribute bug commit_or_recover exists to prevent, and
    # neither gains anything from routing through it.
    "crud.py": 1,  # create_job_type — rolls back, then raises DuplicateJobTypeNameError from exc
    "api/routes/employees.py": 1,  # reset-password — rolls back, returns an already-captured str
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
