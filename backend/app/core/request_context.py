"""Per-request log context: a server-generated request id plus the caller's *verified* identity.

The ContextVar holds ONE mutable dict created per request and is never re-`set()` deeper in the
stack. Starlette documents that BaseHTTPMiddleware (main.py's security-headers middleware is one)
stops ContextVar *changes* propagating back up, and sync route dependencies run in a worker thread
on a *copy* of the context. Mutating a dict both contexts already point at avoids both problems
(pinned by tests/core/test_request_context.py and tests/core/test_request_logging.py).

Identity is bound only by app/api/deps.py after the JWT/profile is verified, never from anything the
client controls (Logging_Cheat_Sheet.md "Attacks on Logs / Accountability": an attacker must not be
able to cause the wrong identity to be logged).
"""

from contextvars import ContextVar
from typing import TypedDict
from uuid import UUID, uuid4

_MAX_ROLE_LEN = 32


class RequestContext(TypedDict):
    request_id: str
    tenant_id: str | None
    actor_id: str | None
    actor_role: str | None


_current: ContextVar[RequestContext | None] = ContextVar("request_context", default=None)


def start_request() -> RequestContext:
    ctx: RequestContext = {
        "request_id": str(uuid4()),
        "tenant_id": None,
        "actor_id": None,
        "actor_role": None,
    }
    _current.set(ctx)
    return ctx


def current() -> RequestContext | None:
    return _current.get()


def _uuid_or_none(value: str | UUID) -> str | None:
    try:
        return str(UUID(str(value)))
    except ValueError:
        return None


def bind_identity(
    *,
    tenant_id: str | UUID | None = None,
    actor_id: str | UUID | None = None,
    actor_role: str | None = None,
) -> None:
    """No-op outside a request. A tenant/actor id that isn't a valid UUID is stored as null, never
    logged raw — a validly-signed but oddly-shaped claim must not put arbitrary text in a log line.
    """
    ctx = _current.get()
    if ctx is None:
        return
    if tenant_id is not None:
        ctx["tenant_id"] = _uuid_or_none(tenant_id)
    if actor_id is not None:
        ctx["actor_id"] = _uuid_or_none(actor_id)
    if actor_role is not None:
        ctx["actor_role"] = actor_role[:_MAX_ROLE_LEN]
