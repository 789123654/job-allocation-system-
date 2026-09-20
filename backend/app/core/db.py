import logging
import threading
import time
from collections.abc import Callable, Generator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import QueuePool
from sqlmodel import Session, create_engine
from sqlmodel import text as sql_text

from app.core.config import settings
from app.models import Profile

# Migrations (Alembic) own schema creation, not create_all() (fastapi/sql-databases.md).
engine = create_engine(
    str(settings.DATABASE_URL),
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    # Without this SQLAlchemy appends `[parameters: {...}]` to every failed statement's message —
    # i.e. a firm's task title/description into Railway logs and Sentry (tests/core/
    # test_db_parameter_hiding.py). The SQL text is kept. Postgres's OWN message can still echo a
    # value; core/redaction.py handles that at the log/Sentry sinks.
    hide_parameters=True,
)

_pool_logger = logging.getLogger("app.pool")


def install_pool_monitor(
    target: Engine,
    *,
    capacity: int,
    warn_ratio: float = 0.7,
    min_interval_seconds: float = 30.0,
) -> None:
    """Warn (logger `app.pool`) when the pool is nearly full. This is the leading indicator the k6
    PATCH run (2026-09-18) showed nothing gives: it went from healthy to `QueuePool limit ...
    reached` with no earlier signal. Fires from the pool's documented `checkout` event;
    rate-limited per engine so a saturated pool warns once per interval, not once per request. A
    listener error must never break a checkout (ASVS 16.5.2), hence the catch-all.
    """
    last_warned = float("-inf")
    lock = threading.Lock()

    def on_checkout(dbapi_connection: object, connection_record: object, proxy: object) -> None:
        nonlocal last_warned
        try:
            pool = target.pool
            if not isinstance(pool, QueuePool):
                return
            checked_out = pool.checkedout()
            utilization = checked_out / capacity
            if utilization < warn_ratio:
                return
            now = time.monotonic()
            with lock:
                if now - last_warned < min_interval_seconds:
                    return
                last_warned = now
            _pool_logger.warning(
                "Database connection pool utilization high",
                extra={
                    "event": "pool_high_utilization",
                    "checked_out": checked_out,
                    "capacity": capacity,
                    "utilization": round(utilization, 3),
                },
            )
        except Exception:
            return

    event.listen(target, "checkout", on_checkout)


install_pool_monitor(
    engine,
    capacity=settings.DB_POOL_SIZE + settings.DB_MAX_OVERFLOW,
    warn_ratio=settings.DB_POOL_WARN_RATIO,
)


def as_aware_utc(value: datetime) -> datetime:
    """Postgres' `timestamptz` round-trips as tz-aware via psycopg, but don't trust that blindly —
    SQLite (this project's own test backend) drops tzinfo on round-trip, and a naive-vs-aware
    comparison raises a raw `TypeError`, not a clean 500. Shared here (moved from crud.py's
    formerly-private `_as_aware_utc`, code-review finding #13's own fix) since idempotency.py needs
    the identical guard for the same reason — both modules already import from this one.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def get_session() -> Generator[Session]:
    # expire_on_commit=False (SQLAlchemy default is True) — every request gets its own fresh
    # session here that never outlives that request (`with Session(...)`, closed at request end),
    # so there's no cross-request staleness risk to trade away. What the default *would* cost:
    # any attribute read on an ORM object after a mid-request commit() silently fires a fresh
    # SELECT to reload it — and get_current_profile's tenant context (`app.current_tenant`,
    # api/deps.py) is deliberately transaction-scoped (SET LOCAL-style), so that implicit SELECT
    # runs with no tenant context at all. Depending on whether the pooled connection had ever seen
    # a tenant context before, that either matched 0 rows or crashed on a raw uuid cast — the real
    # mechanism behind 4 crashes Schemathesis found (2026-09-08, docs/SECURITY_AUDIT_CHECKLIST.md).
    # This is the root-cause fix — it also protects every future create/update handler that
    # commits then returns the object, not just the ones already found and fixed at the call site.
    with Session(engine, expire_on_commit=False) as session:
        yield session


def commit_or_recover(
    session: Session, actor: Profile, on_conflict: Callable[[], Any] | None = None
) -> tuple[bool, Any]:
    """The one place `session.commit()` is allowed to sit inside a `try`/`except IntegrityError` —
    every call site that needs to survive a concurrent identical write racing a UNIQUE/PK
    constraint calls this instead of hand-rolling the shape again. That reimplementation is exactly
    how this project shipped the same bug twice: `_ensure_deadline_notifications` (crud.py) got the
    fix first, then `with_idempotency` (core/idempotency.py) rewrote the same commit/rollback/
    recover shape from scratch and shipped without it — SECURITY_AUDIT_CHECKLIST.md's 2026-09-09
    follow-up. Consolidating here means a future 4th call site has nothing to reimplement.

    The bug itself, restated once, here, not per caller: `Session.rollback()` — unlike `commit()`,
    which `get_session`'s `expire_on_commit=False` above already opts out of — always expires every
    object in the session. Reading an expired attribute (e.g. `actor.firm_id`) afterward fires a
    lazy-refresh SELECT with no RLS tenant context, since that context was scoped to the now-ended
    transaction (`get_current_profile`'s `set_config(..., true)`, api/deps.py). **So: never read an
    ORM attribute off `actor` (or anything else in this session) after calling this — pass `actor`
    itself and read what you need from its return value or from before the call, same as the
    `firm_id_str` capture below.**

    Tenant context is re-established **unconditionally after either branch**, not just on
    conflict — caught by a real two-thread Postgres run while building this helper (an earlier
    version only reset it in the `except`, and the notification-poll concurrency test immediately
    failed with the raw uuid-cast crash on its *clean-commit* path): a successful `commit()` ends
    the `SET LOCAL`-scoped transaction exactly as much as a `rollback()` does, so any caller that
    queries this session again afterward — `_ensure_deadline_notifications`'s own caller,
    `list_notifications`, does — needs it restored either way. A caller with nothing left to do
    just pays one harmless extra `SELECT` on the happy path.

    Returns `(True, None)` on a clean commit, or `(False, on_conflict())` on a conflict — `(False,
    None)` if no `on_conflict` was given, e.g. when the caller has nothing left to do but let the
    next request pick up the missing row (same reasoning `_ensure_deadline_notifications` already
    documents for its own poll-and-retry design).

    Postgres-only re-`set_config`, like `get_current_profile`'s own call — SQLite (used by tests
    that don't need real RLS) has no `set_config` function at all.
    """
    firm_id_str = str(actor.firm_id)
    committed = True
    try:
        session.commit()
    except IntegrityError:
        committed = False
        session.rollback()
    # Before on_conflict() below, not after — on_conflict typically queries the session itself
    # (with_idempotency's winner lookup does), and that query needs context restored first, same as
    # the clean-commit path needs it restored before whatever the caller does next.
    if session.get_bind().dialect.name == "postgresql":
        session.execute(  # pyright: ignore[reportDeprecated] — same as get_current_profile's call
            sql_text("SELECT set_config('app.current_tenant', :firm_id, true)"),
            {"firm_id": firm_id_str},
        )
    recovered = None if committed else (on_conflict() if on_conflict is not None else None)
    return committed, recovered
