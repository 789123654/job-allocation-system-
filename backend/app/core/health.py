"""Readiness: can this instance actually serve a request right now? Unlike /health (liveness only),
which stays green while Postgres is down, so an uptime monitor pointed at it tells you nothing.

Deliberately unauthenticated (an uptime monitor can't present a JWT) and therefore hardened:
- Fixed, detail-free responses — never an exception message, hostname or pool number (ASVS 13.4.5,
  16.5.1). It FAILS CLOSED: any error at all is "not ready" (ASVS 16.5.3).
- Bounded work (Denial_of_Service_Cheat_Sheet.md): one DB probe at most every `ttl_seconds`, and
  never more than ONE probe in flight, so an attacker hammering /ready can't spend DB connections or
  worker threads, and a hung database can't pile up blocked threads (the probe runs on its own
  daemon thread, not anyio's shared worker pool, and never blocks interpreter exit).
- A saturated connection pool is reported immediately instead of queueing behind pool_timeout.
"""

import asyncio
import logging
import threading
import time
from concurrent.futures import Future

from sqlalchemy import text

import app.core.db as db
from app.core import runtime_stats

_logger = logging.getLogger("app.health")
_POLL_SECONDS = 0.02


def _pool_saturated() -> bool:
    checked_out, capacity = runtime_stats.pool_stats()
    return checked_out is not None and capacity is not None and checked_out >= capacity


def _probe_once() -> bool:
    try:
        with db.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        # Class name only: a driver's message can embed the DB host/DSN (Logging_Cheat_Sheet.md
        # "Data to exclude: database connection strings").
        _logger.warning("Readiness probe failed (%s)", type(exc).__name__)
        return False
    return True


class ReadinessProbe:
    def __init__(self, *, ttl_seconds: float = 5.0, timeout_seconds: float = 2.0) -> None:
        self._ttl = ttl_seconds
        self._timeout = timeout_seconds
        self._lock = threading.Lock()
        # Both keyed by the engine they were measured against: a different engine is a different
        # subject, so its result must never be answered from another engine's cache.
        self._cached: tuple[object, bool, float] | None = None
        self._inflight: tuple[object, Future[bool]] | None = None

    def reset(self) -> None:
        with self._lock:
            self._cached = None
            self._inflight = None

    def _start_or_join(self, engine: object) -> Future[bool]:
        inflight = self._inflight
        if inflight is not None and inflight[0] is engine and not inflight[1].done():
            return inflight[1]
        future: Future[bool] = Future()

        def _run() -> None:
            future.set_result(_probe_once())

        threading.Thread(target=_run, daemon=True, name="readiness-probe").start()
        self._inflight = (engine, future)
        return future

    async def check(self) -> bool:
        engine = db.engine
        with self._lock:
            cached = self._cached
            if cached is not None and cached[0] is engine and time.monotonic() < cached[2]:
                return cached[1]
            if _pool_saturated():
                self._cached = (engine, False, time.monotonic() + self._ttl)
                return False
            future = self._start_or_join(engine)

        # Poll instead of asyncio.wrap_future: wrapping would let a timeout CANCEL the concurrent
        # future, marking the still-hung probe "done" and letting a second one start — defeating the
        # one-in-flight bound this class exists to enforce. Polling is also event-loop agnostic.
        deadline = time.monotonic() + self._timeout
        while not future.done() and time.monotonic() < deadline:  # noqa: ASYNC110
            await asyncio.sleep(_POLL_SECONDS)
        ok = future.done() and future.result()

        with self._lock:
            self._cached = (engine, ok, time.monotonic() + self._ttl)
        return ok


readiness_probe = ReadinessProbe()
