from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, EmailStr, Field
from supabase_auth.errors import AuthApiError

from app import crud
from app.api.deps import RequireOwnerDep, SessionDep

router = APIRouter(prefix="/employees", tags=["employees"])

# ponytail: no idempotency-key store exists yet anywhere in this codebase (ARCHITECTURE.md §9
# left the *mechanism* undecided, not just this endpoint) — a duplicate POST here or on
# reset-password creates a second Supabase account / password reset rather than being deduped.
# Real gap, not silently skipped: build the mechanism when a second endpoint needs it too, not a
# bespoke one-off store for this single slice.


class EmployeeCreate(BaseModel):
    # Input_Validation_Cheat_Sheet.md: every string field needs a real length ceiling, not
    # whatever Postgres `text` allows unbounded (API_SPEC.md §4 applies this same rule to
    # tasks/issues text fields; full_name was never given one there — fixed here).
    full_name: str = Field(min_length=1, max_length=200)
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
    offset: Annotated[int, Query(ge=0)] = 0,
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
    employee_id: UUID, actor: RequireOwnerDep, session: SessionDep
) -> GeneratedPassword:
    employee = crud.get_employee(session, employee_id)
    if employee is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")
    password = crud.reset_employee_password(session, actor, employee)
    return GeneratedPassword(generated_password=password)
