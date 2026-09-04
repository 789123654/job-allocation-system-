from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field
from supabase_auth.errors import AuthApiError

from app import crud
from app.api.deps import RequireOwnerDep, SessionDep
from app.core.idempotency import with_idempotency

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
    employee_id: UUID,
    actor: RequireOwnerDep,
    session: SessionDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> JSONResponse:
    employee = crud.get_employee(session, employee_id)
    if employee is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")

    def _handler() -> tuple[int, dict[str, Any]]:
        password = crud.reset_employee_password(session, actor, employee)
        return status.HTTP_200_OK, GeneratedPassword(generated_password=password).model_dump(
            mode="json"
        )

    status_code, response_body = with_idempotency(
        session,
        actor,
        idempotency_key,
        f"POST /employees/{employee_id}/reset-password",
        {},
        _handler,
    )
    return JSONResponse(status_code=status_code, content=response_body)
