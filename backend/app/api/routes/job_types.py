from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app import crud
from app.api.deps import ActiveProfileDep, RequireOwnerDep, SessionDep
from app.core.validation import NoNulStr

router = APIRouter(prefix="/job-types", tags=["job-types"])


class JobTypeCreate(BaseModel):
    # Input_Validation_Cheat_Sheet.md: every string field needs a real length ceiling (same rule
    # already applied to EmployeeCreate.full_name, re-checked fresh for this field 2026-09-04).
    name: NoNulStr = Field(min_length=1, max_length=200)


class JobTypeOut(BaseModel):
    id: UUID
    name: str
    is_active: bool


class JobTypeUpdate(BaseModel):
    is_active: bool


@router.post("", status_code=status.HTTP_201_CREATED)
def create_job_type(body: JobTypeCreate, actor: RequireOwnerDep, session: SessionDep) -> JobTypeOut:
    try:
        job_type = crud.create_job_type(session, actor, body.name)
    except crud.DuplicateJobTypeNameError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Job type name already in use") from exc
    return JobTypeOut(id=job_type.id, name=job_type.name, is_active=job_type.is_active)


@router.get("")
def list_job_types(
    actor: ActiveProfileDep,
    session: SessionDep,
    # le bound: same reasoning as tasks.py's list_tasks — Postgres bigint OFFSET overflow
    # otherwise crashes with a raw 500 instead of a clean 422 (found by Schemathesis, 2026-09-08).
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[JobTypeOut]:
    job_types = crud.list_job_types(session, actor, offset, limit)
    return [JobTypeOut(id=jt.id, name=jt.name, is_active=jt.is_active) for jt in job_types]


@router.patch("/{job_type_id}")
def update_job_type(
    job_type_id: UUID, body: JobTypeUpdate, actor: RequireOwnerDep, session: SessionDep
) -> JobTypeOut:
    job_type = crud.get_job_type(session, actor, job_type_id)
    if job_type is None:
        # 404, not 403 — same reasoning as Employees' update route (ASVS access-control principle,
        # API_SPEC.md §3): an Owner probing another firm's job type id learns nothing.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job type not found")
    job_type = crud.set_job_type_active(session, job_type, body.is_active)
    return JobTypeOut(id=job_type.id, name=job_type.name, is_active=job_type.is_active)
