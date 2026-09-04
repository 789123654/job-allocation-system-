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
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models import IdempotencyKey, Profile

_TTL = timedelta(hours=24)  # Rule 230's own example duration; not prescribed, just a sane default


def _hash_request(endpoint: str, body: dict[str, Any]) -> str:
    canonical = json.dumps(body, sort_keys=True, default=str)
    return hashlib.sha256(f"{endpoint}:{canonical}".encode()).hexdigest()


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
    try:
        session.commit()
    except IntegrityError:
        # A concurrent identical retry won the race first — not a real error, refetch its result.
        session.rollback()
        winner = session.exec(
            select(IdempotencyKey).where(
                IdempotencyKey.firm_id == actor.firm_id,
                IdempotencyKey.actor_id == actor.id,
                IdempotencyKey.idempotency_key == idempotency_key,
                IdempotencyKey.endpoint == endpoint,
            )
        ).first()
        if winner is None:
            raise
        return winner.response_status, winner.response_body
    return status_code, response_body
