import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlmodel import select
from supabase_auth.errors import AuthApiError, AuthError

from app import crud
from app.api.deps import IdempotencyKeyHeader, RequireOwnerDep, SessionDep
from app.core.db import commit_or_recover
from app.core.idempotency import record_idempotency_key, reject_if_idempotency_key_used
from app.core.validation import LimitQuery, NoNulStr, OffsetQuery
from app.models import IdempotencyKey

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/employees", tags=["employees"])

# `POST ""` uses email's own uniqueness as its dedup key — API_SPEC.md's assigned "Secondary key"
# pattern (rest-api-guidelines Rule 231, re-checked 2026-09-04, not assumed): a retry with the
# same email hits Supabase's global auth.users uniqueness and gets mapped to 409 below, which is
# exactly what Rule 229 asks a secondary key to do ("expose conflicts and prevent resource
# duplicate") — it does not promise the retry replays the original success response, only that it
# can't create a second account. No Idempotency-Key infra needed here, unlike reset-password below.


class EmployeeCreate(BaseModel):
    # Input_Validation_Cheat_Sheet.md: every string field needs a real length ceiling, not
    # whatever Postgres `text` allows unbounded (API_SPEC.md §4 applies this same rule to
    # tasks/issues text fields; full_name was never given one there — fixed here).
    full_name: NoNulStr = Field(min_length=1, max_length=200)
    email: EmailStr


class EmployeeCreated(BaseModel):
    id: UUID
    full_name: str
    email: str
    generated_password: str


class EmployeeOut(BaseModel):
    id: UUID
    full_name: str
    email: str
    is_active: bool
    pending_job_count: int = 0


class EmployeeUpdate(BaseModel):
    is_active: bool


class GeneratedPassword(BaseModel):
    generated_password: str


@router.post("", status_code=status.HTTP_201_CREATED)
def create_employee(
    body: EmployeeCreate, actor: RequireOwnerDep, session: SessionDep
) -> EmployeeCreated:
    try:
        new_id, password = crud.create_employee(session, actor, body.full_name, body.email)
    except AuthApiError as exc:
        # Never relay Supabase's own error text verbatim (API_SPEC.md §1 Rule 177) — email
        # collision is the only realistic cause at this call site (global uniqueness on
        # auth.users.email, DATA_MODEL.md §1), so it's the only case named specifically.
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already in use") from exc
    except AuthError as exc:
        # Any other Supabase Auth failure (e.g. AuthWeakPasswordError — not a subclass of
        # AuthApiError, so the narrower except above never caught it; this was the actual cause of
        # an unhandled 500 found in manual testing, 2026-09-16, now fixed at the source in
        # crud._generate_password — this is the belt-and-suspenders catch-all for anything else).
        logger.error("Supabase admin.create_user failed: %s", exc)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "Could not create employee account"
        ) from exc
    return EmployeeCreated(
        id=new_id, full_name=body.full_name, email=body.email, generated_password=password
    )


@router.get("")
def list_employees(
    actor: RequireOwnerDep,
    session: SessionDep,
    offset: OffsetQuery = 0,
    limit: LimitQuery = 20,
) -> list[EmployeeOut]:
    # Pending-job workload count (PRD §2.4) — deferred when this route was first written (Phase 1,
    # before `tasks` existed); added now that Phase 4's Dashboard slice actually needs it.
    employees = crud.list_employees(session, actor, offset, limit)
    out: list[EmployeeOut] = []
    for e, count in employees:
        # Only pending_job_count needs the manual override — it comes from crud.list_employees'
        # separate workload subquery, not from a Profile attribute (code-review finding #7).
        employee_out = EmployeeOut.model_validate(e, from_attributes=True)
        employee_out.pending_job_count = count
        out.append(employee_out)
    return out


@router.patch("/{employee_id}")
def update_employee(
    employee_id: UUID, body: EmployeeUpdate, actor: RequireOwnerDep, session: SessionDep
) -> EmployeeOut:
    employee = crud.get_employee(session, actor, employee_id)
    if employee is None:
        # 404, not 403 — an Owner probing another firm's employee id learns nothing (ASVS
        # access-control principle already applied elsewhere in API_SPEC.md §3).
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")
    employee = crud.set_employee_active(session, actor, employee, body.is_active)
    return EmployeeOut.model_validate(employee, from_attributes=True)


@router.post("/{employee_id}/reset-password")
def reset_password(
    employee_id: UUID,
    actor: RequireOwnerDep,
    session: SessionDep,
    idempotency_key: IdempotencyKeyHeader,
) -> GeneratedPassword:
    """Deliberately NOT `with_idempotency` (core/idempotency.py) — caught 2026-09-04 re-auditing
    this exact endpoint: that helper caches and replays the exact response body, which would
    persist this one-time generated password in `idempotency_keys` for 24h and make it
    retrievable a second time — directly contradicting this endpoint's own documented invariant
    (API_SPEC.md §3: "the only time it's ever transmitted... never retrievable again after this
    response"). Business_Logic_Security_Cheat_Sheet.md's "Reject Replays of Completed Steps"
    supports rejecting a replay outright rather than serving a cached secret. Trade-off, stated
    plainly: this endpoint no longer satisfies Rule 230's "exact same response" guarantee — a
    retry gets an explanatory 409, not the original password — deliberate, not a default from
    skipping the check.
    """
    employee = crud.get_employee(session, actor, employee_id)
    if employee is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")

    endpoint = f"POST /employees/{employee_id}/reset-password"
    reject_if_idempotency_key_used(session, actor, idempotency_key, endpoint)

    try:
        password = crud.reset_employee_password(session, actor, employee)
    except AuthError as exc:
        # Same belt-and-suspenders catch as create_employee above — this call goes through the
        # same crud._generate_password (already fixed at the source), but a raw Supabase Auth
        # failure of any kind should never reach the client as an unhandled 500.
        logger.error("Supabase admin.update_user_by_id failed: %s", exc)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "Could not reset employee password"
        ) from exc
    record_idempotency_key(
        session,
        actor,
        idempotency_key,
        endpoint,
        {"generated_password": "[redacted — shown once, not cached]"},
    )
    committed, existing_key = commit_or_recover(
        session,
        actor,
        on_conflict=lambda: session.exec(
            select(IdempotencyKey).where(
                IdempotencyKey.firm_id == actor.firm_id,
                IdempotencyKey.actor_id == actor.id,
                IdempotencyKey.idempotency_key == idempotency_key,
                IdempotencyKey.endpoint == endpoint,
            )
        ).first(),
    )
    if not committed and existing_key is None:
        # The expected benign race (a concurrent identical retry won the insert first) always
        # leaves an IdempotencyKey row behind, since it's that other request's own successful
        # commit that caused this one's insert to collide. If no such row exists, the commit
        # failed for some other reason — the employee's password already changed on Supabase's
        # side, but nothing here recorded it (no audit log, no must_change_password flip). Found
        # in code review, 2026-09-14: the previous version treated *every* commit failure as the
        # one specific benign race, without checking that assumption actually held.
        logger.error(
            "reset-password commit failed for a reason other than a concurrent identical "
            "retry (employee=%s) — Supabase password was rotated but no local record exists",
            employee.id,
        )
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Password reset may not have completed correctly — check the employee's audit "
            "history before retrying.",
        )
    return GeneratedPassword(generated_password=password)
