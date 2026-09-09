"""Idempotency-Key header handling — rest-api-guidelines Rule 230, checked directly 2026-09-04
(http-headers.md:216), not assumed from the general concept. A client-specific key, stored
temporarily with the request hash and the exact response, replayed verbatim on retry; 400 if the
same key gets reused with a different request body.

One shared helper rather than duplicated per-route logic — every endpoint that needs this
(POST /tasks, /tasks/{id}/submit, /tasks/{id}/mark-billed, API_SPEC.md) wraps its business logic
in `with_idempotency` instead of hand-rolling the check/store dance three times.
"""

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlmodel import Session, select

from app.core.db import commit_or_recover
from app.models import IdempotencyKey, Profile

_TTL = timedelta(hours=24)  # Rule 230's own example duration; not prescribed, just a sane default


def _hash_request(endpoint: str, body: dict[str, Any]) -> str:
    canonical = json.dumps(body, sort_keys=True, default=str)
    return hashlib.sha256(f"{endpoint}:{canonical}".encode()).hexdigest()


def reject_if_idempotency_key_used(
    session: Session, actor: Profile, idempotency_key: str, endpoint: str
) -> None:
    """For an endpoint whose response is a one-time secret, where `with_idempotency`'s cache-
    and-replay would persist it past its single intended transmission (API_SPEC.md §3) — this
    only dedupes: a retry gets 409, never the original response. Call before the real work; call
    `record_idempotency_key` after, in the same transaction as that work's own commit — moved out
    of employees.py's reset-password route (2026-09-05) to satisfy CODING_STRUCTURE.md's "route
    calls crud.py [or this module] only, no inline queries," same rule every other slice follows.
    """
    existing = session.exec(
        select(IdempotencyKey).where(
            IdempotencyKey.firm_id == actor.firm_id,
            IdempotencyKey.actor_id == actor.id,
            IdempotencyKey.idempotency_key == idempotency_key,
            IdempotencyKey.endpoint == endpoint,
        )
    ).first()
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Already processed with this Idempotency-Key — the response was shown once and "
            "cannot be retrieved again; retry with a new Idempotency-Key for a new one.",
        )


def record_idempotency_key(
    session: Session,
    actor: Profile,
    idempotency_key: str,
    endpoint: str,
    redacted_response_body: dict[str, Any],
) -> None:
    """Pairs with `reject_if_idempotency_key_used` — session.add() only, no commit, so it lands in
    the caller's own transaction alongside the real work's writes (same reasoning as
    `with_idempotency`'s own handler contract).
    """
    session.add(
        IdempotencyKey(
            firm_id=actor.firm_id,
            actor_id=actor.id,
            idempotency_key=idempotency_key,
            endpoint=endpoint,
            request_hash="",  # no request body ever varies on this class of bodyless POST
            response_status=status.HTTP_200_OK,
            response_body=redacted_response_body,
            created_at=datetime.now(UTC),
        )
    )


def with_idempotency(
    session: Session,
    actor: Profile,
    idempotency_key: str,
    endpoint: str,
    request_body: dict[str, Any],
    handler: Callable[[], tuple[int, dict[str, Any]]],
) -> tuple[int, dict[str, Any]]:
    """`handler` does the real work — `session.add(...)` only, no `commit()` — so its write and
    the idempotency-cache row land in one transaction (Rule 230's "hard transaction semantics",
    made cheap here since this is a single Postgres instance, not a distributed system).

    ponytail: Rule 230 says cache the response "regardless of whether it succeeded or failed" —
    this only caches on success (an `HTTPException` raised inside `handler` propagates straight
    out, skipping the cache write). Acceptable at this project's scale because every current
    failure case (a workflow-state 409) is already deterministic from the row's current state, so
    a retry gets the same rejection without needing it cached — upgrade to catching and caching
    `HTTPException` too if a future failure case is ever non-deterministic (e.g. a transient
    external-API error) where retry-and-recompute could legitimately give a different answer.
    """
    actor_id = actor.id
    request_hash = _hash_request(endpoint, request_body)
    cutoff = datetime.now(UTC) - _TTL
    existing = session.exec(
        select(IdempotencyKey).where(
            IdempotencyKey.firm_id == actor.firm_id,
            IdempotencyKey.actor_id == actor.id,
            IdempotencyKey.idempotency_key == idempotency_key,
            IdempotencyKey.endpoint == endpoint,
            IdempotencyKey.created_at > cutoff,
        )
    ).first()
    if existing is not None:
        if existing.request_hash != request_hash:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Idempotency-Key reused with a different request"
            )
        return existing.response_status, existing.response_body

    status_code, response_body = handler()
    session.add(
        IdempotencyKey(
            firm_id=actor.firm_id,
            actor_id=actor.id,
            idempotency_key=idempotency_key,
            endpoint=endpoint,
            request_hash=request_hash,
            response_status=status_code,
            response_body=response_body,
            created_at=datetime.now(UTC),
        )
    )

    firm_id_str = str(actor.firm_id)

    def _recover_winner() -> tuple[int, dict[str, Any]]:
        # Called by commit_or_recover (core/db.py) only after it has already rolled back and
        # re-established tenant context — safe to query the session again here for that reason.
        # A concurrent identical retry won the insert race first — not a real error, refetch it.
        winner = session.exec(
            select(IdempotencyKey).where(
                IdempotencyKey.firm_id == firm_id_str,
                IdempotencyKey.actor_id == actor_id,
                IdempotencyKey.idempotency_key == idempotency_key,
                IdempotencyKey.endpoint == endpoint,
            )
        ).first()
        if winner is None:
            # Genuinely shouldn't happen — a UNIQUE-constraint IntegrityError with no matching row
            # after it. Not a bare `raise`: commit_or_recover (core/db.py) calls on_conflict()
            # after its own except block has already exited (needed so tenant context is restored
            # before this query runs), so there's no "currently handled exception" left to re-raise
            # by that point — confirmed empirically while writing this, not assumed.
            raise RuntimeError(
                "IntegrityError on idempotency_keys but no winning row found afterward — should "
                "be impossible; the UNIQUE constraint that raised it implies a matching row exists."
            )
        return winner.response_status, winner.response_body

    committed, recovered = commit_or_recover(session, actor, on_conflict=_recover_winner)
    if not committed:
        return recovered
    return status_code, response_body
