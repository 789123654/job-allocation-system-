from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.exc import IntegrityError
from supabase_auth.errors import AuthApiError

from app import crud
from app.api.deps import IdempotencyKeyHeader, RequireOwnerDep, SessionDep
from app.core.idempotency import record_idempotency_key, reject_if_idempotency_key_used
from app.core.validation import NoNulStr

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
    return EmployeeCreated(
        id=new_id, full_name=body.full_name, email=body.email, generated_password=password
    )


@router.get("")
def list_employees(
    actor: RequireOwnerDep,
    session: SessionDep,
    # le bound: same reasoning as tasks.py's list_tasks — Postgres bigint OFFSET overflow
    # otherwise crashes with a raw 500 instead of a clean 422 (found by Schemathesis, 2026-09-08).
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[EmployeeOut]:
    # Pending-job workload count (PRD §2.4) needs `tasks`, which doesn't exist until Phase 3 —
    # deliberately omitted here, not silently dropped (CODING_STRUCTURE.md's vertical-slice order).
    employees = crud.list_employees(session, offset, limit)
    return [
        EmployeeOut(id=e.id, full_name=e.full_name, email=e.email, is_active=e.is_active)
        for e in employees
    ]


@router.patch("/{employee_id}")
def update_employee(
    employee_id: UUID, body: EmployeeUpdate, actor: RequireOwnerDep, session: SessionDep
) -> EmployeeOut:
    employee = crud.get_employee(session, employee_id)
    if employee is None:
        # 404, not 403 — an Owner probing another firm's employee id learns nothing (ASVS
        # access-control principle already applied elsewhere in API_SPEC.md §3).
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")
    employee = crud.set_employee_active(session, actor, employee, body.is_active)
    return EmployeeOut(
        id=employee.id,
        full_name=employee.full_name,
        email=employee.email,
        is_active=employee.is_active,
    )


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
    employee = crud.get_employee(session, employee_id)
    if employee is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")

    endpoint = f"POST /employees/{employee_id}/reset-password"
    reject_if_idempotency_key_used(session, actor, idempotency_key, endpoint)

    password = crud.reset_employee_password(session, actor, employee)
    record_idempotency_key(
        session,
        actor,
        idempotency_key,
        endpoint,
        {"generated_password": "[redacted — shown once, not cached]"},
    )
    try:
        session.commit()
    except IntegrityError:
        # A concurrent identical retry won the insert race first — this call's own password is
        # still real and still the only response this caller sees (same accepted true-concurrent-
        # race caveat as with_idempotency's own docstring: sequential retries are fully protected,
        # two genuinely simultaneous calls can still both reach Supabase).
        session.rollback()
    return GeneratedPassword(generated_password=password)
