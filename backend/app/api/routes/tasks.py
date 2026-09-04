from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app import crud
from app.api.deps import ActiveProfileDep, RequireOwnerDep, SessionDep
from app.core.idempotency import with_idempotency
from app.models import Task

router = APIRouter(prefix="/tasks", tags=["tasks"])


class TaskCreate(BaseModel):
    # Input_Validation_Cheat_Sheet.md length-ceiling rule, re-checked fresh for these two fields
    # (2026-09-04) — same rule already applied to full_name/job_types.name, not assumed to
    # transfer automatically. No skill specifies the exact numbers; these are project judgment.
    title: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=5000)
    job_type_id: UUID | None = None
    assigned_to: UUID | None = None
    deadline: datetime | None = None


class TaskOut(BaseModel):
    id: UUID
    job_type_id: UUID | None
    task_type: str
    parent_task_id: UUID | None
    title: str
    description: str | None
    assigned_to: UUID | None
    deadline: datetime | None
    status: str
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    last_reassignment_notes: str | None
    last_reassignment_remaining_work: str | None
    last_reassignment_source: str | None
    last_reassignment_at: datetime | None
    billing_amount: float | None
    billing_recipient: str | None

    @classmethod
    def from_task(cls, task: Task) -> "TaskOut":
        return cls(
            id=task.id,
            job_type_id=task.job_type_id,
            task_type=task.task_type,
            parent_task_id=task.parent_task_id,
            title=task.title,
            description=task.description,
            assigned_to=task.assigned_to,
            deadline=task.deadline,
            status=task.status,
            created_by=task.created_by,
            created_at=task.created_at,
            updated_at=task.updated_at,
            last_reassignment_notes=task.last_reassignment_notes,
            last_reassignment_remaining_work=task.last_reassignment_remaining_work,
            last_reassignment_source=task.last_reassignment_source,
            last_reassignment_at=task.last_reassignment_at,
            billing_amount=task.billing_amount,
            billing_recipient=task.billing_recipient,
        )


class TaskDeadlineUpdate(BaseModel):
    deadline: datetime


# response_model isn't declared on the two Idempotency-Key routes below — they return a
# JSONResponse directly (the exact cached body on a replay, not a freshly re-validated one), so
# FastAPI can't apply response_model to it. Documented trade-off, not an oversight: this project
# has no OpenAPI-schema consumer yet (a hand-built React frontend, not a generated client).


@router.post("", status_code=status.HTTP_201_CREATED)
def create_task(
    body: TaskCreate,
    actor: RequireOwnerDep,
    session: SessionDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> JSONResponse:
    def _handler() -> tuple[int, dict[str, Any]]:
        task = crud.create_task(
            session,
            actor,
            body.title,
            body.description,
            body.job_type_id,
            body.assigned_to,
            body.deadline,
        )
        session.flush()  # assigns task.id within the still-open transaction, before commit
        return status.HTTP_201_CREATED, TaskOut.from_task(task).model_dump(mode="json")

    status_code, response_body = with_idempotency(
        session, actor, idempotency_key, "POST /tasks", body.model_dump(mode="json"), _handler
    )
    return JSONResponse(status_code=status_code, content=response_body)


@router.get("")
def list_tasks(
    actor: ActiveProfileDep,
    session: SessionDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    assigned_to: Annotated[UUID | None, Query()] = None,
    job_type_id: Annotated[UUID | None, Query()] = None,
    task_type: Annotated[str | None, Query()] = None,
) -> list[TaskOut]:
    tasks = crud.list_tasks(
        session, actor, offset, limit, status_filter, assigned_to, job_type_id, task_type
    )
    return [TaskOut.from_task(t) for t in tasks]


@router.get("/{task_id}")
def get_task(task_id: UUID, actor: ActiveProfileDep, session: SessionDep) -> TaskOut:
    task = crud.get_task(session, actor, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    return TaskOut.from_task(task)


@router.patch("/{task_id}/deadline")
def update_task_deadline(
    task_id: UUID, body: TaskDeadlineUpdate, actor: RequireOwnerDep, session: SessionDep
) -> TaskOut:
    task = crud.get_task(session, actor, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    task = crud.update_task_deadline(session, task, body.deadline)
    return TaskOut.from_task(task)


@router.post("/{task_id}/submit")
def submit_task(
    task_id: UUID,
    actor: ActiveProfileDep,
    session: SessionDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> JSONResponse:
    task = crud.get_task(session, actor, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    # Visible-to (get_task's own rule) is broader than authorized-to-act-on — an Owner can see
    # every task in the firm but isn't the "assigned employee" this action is scoped to
    # (API_SPEC.md). Real 403 here, not 404: the task's existence is already legitimately known.
    if actor.role != "employee" or task.assigned_to != actor.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the assigned employee can submit this task"
        )

    def _handler() -> tuple[int, dict[str, Any]]:
        try:
            updated = crud.submit_task(session, task)
        except crud.InvalidTaskStateError as exc:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Task cannot be submitted from its current status"
            ) from exc
        return status.HTTP_200_OK, TaskOut.from_task(updated).model_dump(mode="json")

    status_code, response_body = with_idempotency(
        session, actor, idempotency_key, f"POST /tasks/{task_id}/submit", {}, _handler
    )
    return JSONResponse(status_code=status_code, content=response_body)


@router.post("/{task_id}/mark-billed")
def mark_task_billed(
    task_id: UUID,
    actor: ActiveProfileDep,
    session: SessionDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> JSONResponse:
    task = crud.get_task(session, actor, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    if actor.role != "employee" or task.assigned_to != actor.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the assigned employee can mark this task billed"
        )

    def _handler() -> tuple[int, dict[str, Any]]:
        try:
            updated = crud.mark_task_billed(session, task)
        except crud.InvalidTaskStateError as exc:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Task cannot be marked billed — wrong task_type or status",
            ) from exc
        return status.HTTP_200_OK, TaskOut.from_task(updated).model_dump(mode="json")

    status_code, response_body = with_idempotency(
        session, actor, idempotency_key, f"POST /tasks/{task_id}/mark-billed", {}, _handler
    )
    return JSONResponse(status_code=status_code, content=response_body)
