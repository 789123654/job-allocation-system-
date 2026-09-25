"""The per-request identity holder that log lines read (app/core/request_context.py).

Each test body runs in a brand-new empty contextvars.Context so a previous test's request context
can never be what's "current" — the same isolation property the holder must give real requests.
"""

import contextvars
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from app.core import request_context


def _isolated(fn: Callable[[], None]) -> None:
    contextvars.Context().run(fn)


def test_bind_outside_a_request_is_a_harmless_noop() -> None:
    def body() -> None:
        assert request_context.current() is None
        request_context.bind_identity(tenant_id=str(uuid4()), actor_role="owner")  # must not raise
        assert request_context.current() is None

    _isolated(body)


def test_each_request_gets_a_fresh_uuid4_and_no_identity() -> None:
    def body() -> None:
        first = request_context.start_request()
        request_context.bind_identity(tenant_id=str(uuid4()), actor_id=uuid4(), actor_role="owner")
        second = request_context.start_request()
        assert first["request_id"] != second["request_id"]
        assert (second["tenant_id"], second["actor_id"], second["actor_role"]) == (None, None, None)
        # The earlier request's context object is untouched by the later one.
        assert first["tenant_id"] is not None

    _isolated(body)


def test_bind_canonicalises_valid_uuids_and_drops_everything_else() -> None:
    def body() -> None:
        ctx = request_context.start_request()
        tid = uuid4()
        request_context.bind_identity(tenant_id="{" + str(tid).upper() + "}", actor_id=tid)
        assert ctx["tenant_id"] == str(tid)
        assert ctx["actor_id"] == str(tid)

        # A validly-signed but oddly-shaped claim must never put arbitrary text into a log line.
        request_context.bind_identity(tenant_id='not-a-uuid"}\n{"forged": true', actor_id="x" * 500)
        assert ctx["tenant_id"] is None
        assert ctx["actor_id"] is None

    _isolated(body)


def test_role_is_length_clipped() -> None:
    def body() -> None:
        ctx = request_context.start_request()
        request_context.bind_identity(actor_role="r" * 500)
        assert ctx["actor_role"] is not None
        assert len(ctx["actor_role"]) == 32

    _isolated(body)


def test_a_worker_thread_on_a_copied_context_mutates_the_same_holder() -> None:
    """Sync route dependencies run in a worker thread on a COPY of the context. The design only
    works because the copy still points at the one mutable dict — this pins exactly that.
    """

    def body() -> None:
        ctx = request_context.start_request()
        tid = uuid4()
        copied = contextvars.copy_context()
        with ThreadPoolExecutor(1) as pool:
            pool.submit(
                copied.run, lambda: request_context.bind_identity(tenant_id=tid, actor_role="owner")
            ).result()
        assert ctx["tenant_id"] == str(tid)
        assert ctx["actor_role"] == "owner"

    _isolated(body)
