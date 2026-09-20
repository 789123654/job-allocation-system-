"""Point-in-time capacity readings: the two saturation signals whose exhaustion the k6 PATCH run
(2026-09-18) hit with no earlier warning — the DB connection pool and anyio's worker-thread limiter.

One place computes them so the access log, the readiness probe and the pool monitor can never
disagree about what "full" means (code-review root cause A: a rule re-derived at each call site).
"""

import anyio.to_thread
from sqlalchemy.pool import QueuePool

import app.core.db as db  # `db.engine` looked up at call time, so a substituted engine is honoured


def pool_stats() -> tuple[int | None, int | None]:
    """(checked_out, capacity) of the live engine's pool; (None, None) if it isn't a QueuePool.

    `checkedout()`/`size()`/`_max_overflow` aren't in SQLAlchemy's documented pool API (only
    `status()` is; checked against the 2.0 docs) — they exist in the installed source and
    tests/core/test_runtime_stats.py pins them, so an upgrade that renames one fails loudly.
    """
    pool = getattr(db.engine, "pool", None)
    if not isinstance(pool, QueuePool):
        return None, None
    return pool.checkedout(), pool.size() + pool._max_overflow  # pyright: ignore[reportPrivateUsage]


def threadpool_stats() -> tuple[int | None, int | None]:
    """(borrowed, total) tokens of anyio's default worker-thread limiter (40 by default per anyio's
    docs). Only valid inside a running event loop — anyio raises otherwise, hence the fallback.
    """
    try:
        limiter = anyio.to_thread.current_default_thread_limiter()
        return int(limiter.borrowed_tokens), int(limiter.total_tokens)
    except Exception:
        return None, None
