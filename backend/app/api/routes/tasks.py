from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator

from app import crud
from app.api.deps import ActiveProfileDep, IdempotencyKeyHeader, RequireOwnerDep, SessionDep
from app.core.idempotency import with_idempotency
from app.models import Issue, Profile, Task

router = APIRouter(prefix="/tasks", tags=["tasks"])

_TASK_NOT_FOUND = "Task not found"


def _get_task_or_404(session: SessionDep, actor: Profile, task_id: UUID) -> Task:
    task = crud.get_task(session, actor, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _TASK_NOT_FOUND)
    return task


def _require_assignee(session: SessionDep, actor: Profile, task: Task, action: str) -> None:
    # Visible-to (get_task's own rule) is broader than authorized-to-act-on — an Owner can see
    # every task in the firm but isn't the "assigned employee" these actions are scoped to
    # (API_SPEC.md). Real 403 here, not 404: the task's existence is already legitimately known.
    if actor.role != "employee" or task.assigned_to != actor.id:
        crud.record_access_denial(session, actor, "task", task.id, "not_assignee")
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Only the assigned employee can {action}")


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


class TaskReviewCreate(BaseModel):
    outcome: Literal["approved", "reassigned", "billing"]
    notes: str | None = Field(default=None, max_length=2000)
    # 'reassigned' fields
    remaining_work_description: str | None = Field(default=None, max_length=2000)
    assigned_to: UUID | None = None
    # 'billing' fields — all required together when outcome='billing', enforced below
    billing_deadline: datetime | None = None
    billing_description: str | None = Field(default=None, max_length=5000)
    billing_amount: float | None = Field(default=None, gt=0)
    billing_recipient: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _validate_outcome_fields(self) -> "TaskReviewCreate":
        # Business_Logic_Security_Cheat_Sheet.md "Validate Combinations" (checked 2026-09-04) —
        # each field is individually well-formed but only meaningful for its own outcome; a field
        # from another outcome silently accepted here would be exactly the "don't trust hidden/
        # derived fields" gap the cheat sheet warns about.
        billing_fields_set = any(
            v is not None
            for v in (
                self.billing_deadline,
                self.billing_description,
                self.billing_amount,
                self.billing_recipient,
            )
        )
        if self.outcome == "reassigned":
            if not self.remaining_work_description:
                raise ValueError("remaining_work_description is required for outcome=reassigned")
            if billing_fields_set:
                raise ValueError("billing fields are only valid for outcome=billing")
        elif self.outcome == "billing":
            if not (
                self.assigned_to
                and self.billing_deadline
                and self.billing_description
                and self.billing_amount
                and self.billing_recipient
            ):
                raise ValueError(
                    "assigned_to, billing_deadline, billing_description, billing_amount, and "
                    "billing_recipient are all required for outcome=billing"
                )
            if self.remaining_work_description:
                raise ValueError("remaining_work_description is only valid for outcome=reassigned")
        else:  # approved
            if self.remaining_work_description or self.assigned_to or billing_fields_set:
                raise ValueError("only 'notes' is valid for outcome=approved")
        return self


class IssueCreate(BaseModel):
    description: str = Field(min_length=1, max_length=2000)


class IssueOut(BaseModel):
    id: UUID
    task_id: UUID
    raised_by: UUID
    description: str
    status: str
    resolution_type: str | None
    resolution_notes: str | None
    remaining_work_description: str | None
    resolved_by: UUID | None
    resolved_at: datetime | None
    created_at: datetime

    @classmethod
    def from_issue(cls, issue: Issue) -> "IssueOut":
        return cls(
            id=issue.id,
            task_id=issue.task_id,
            raised_by=issue.raised_by,
            description=issue.description,
            status=issue.status,
            resolution_type=issue.resolution_type,
            resolution_notes=issue.resolution_notes,
            remaining_work_description=issue.remaining_work_description,
            resolved_by=issue.resolved_by,
            resolved_at=issue.resolved_at,
            created_at=issue.created_at,
        )


# response_model isn't declared on the two Idempotency-Key routes below — they return a
# JSONResponse directly (the exact cached body on a replay, not a freshly re-validated one), so
# FastAPI can't apply response_model to it. Documented trade-off, not an oversight: this project
# has no OpenAPI-schema consumer yet (a hand-built React frontend, not a generated client).


@router.post("", status_code=status.HTTP_201_CREATED)
def create_task(
    body: TaskCreate,
    actor: RequireOwnerDep,
    session: SessionDep,
    idempotency_key: IdempotencyKeyHeader,
) -> JSONResponse:
    def _handler() -> tuple[int, dict[str, Any]]:
        try:
            task = crud.create_task(
                session,
                actor,
                body.title,
                body.description,
                body.job_type_id,
                body.assigned_to,
                body.deadline,
            )
        except crud.UnknownAssigneeError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "assigned_to must be an active employee of this firm",
            ) from exc
        except crud.UnknownJobTypeError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "job_type_id must be an active job type of this firm",
            ) from exc
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
    # le bound: Input_Validation_Cheat_Sheet.md's "minimum and maximum value range check for
    # numerical parameters" — without it, Postgres's own bigint OFFSET clause overflows on a
    # large-enough value (max 9223372036854775807) and crashes with a raw 500 instead of a clean
    # 422. 1,000,000 is a generous ceiling for this project's actual scale (found by Schemathesis,
    # 2026-09-08, docs/SECURITY_AUDIT_CHECKLIST.md — same fix applied to every list endpoint).
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
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
    task = _get_task_or_404(session, actor, task_id)
    return TaskOut.from_task(task)


@router.patch("/{task_id}/deadline")
def update_task_deadline(
    task_id: UUID, body: TaskDeadlineUpdate, actor: RequireOwnerDep, session: SessionDep
) -> TaskOut:
    task = _get_task_or_404(session, actor, task_id)
    task = crud.update_task_deadline(session, task, body.deadline)
    return TaskOut.from_task(task)


@router.post("/{task_id}/submit")
def submit_task(
    task_id: UUID,
    actor: ActiveProfileDep,
    session: SessionDep,
    idempotency_key: IdempotencyKeyHeader,
) -> JSONResponse:
    task = _get_task_or_404(session, actor, task_id)
    _require_assignee(session, actor, task, "submit this task")

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
    idempotency_key: IdempotencyKeyHeader,
) -> JSONResponse:
    task = _get_task_or_404(session, actor, task_id)
    _require_assignee(session, actor, task, "mark this task billed")

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


@router.post("/{task_id}/review")
def review_task(
    task_id: UUID,
    body: TaskReviewCreate,
    actor: RequireOwnerDep,
    session: SessionDep,
    idempotency_key: IdempotencyKeyHeader,
) -> JSONResponse:
    task = _get_task_or_404(session, actor, task_id)

    def _handler() -> tuple[int, dict[str, Any]]:
        try:
            _, updated = crud.create_task_review(
                session,
                actor,
                task,
                body.outcome,
                body.notes,
                body.remaining_work_description,
                body.assigned_to,
                body.billing_deadline,
                body.billing_description,
                body.billing_amount,
                body.billing_recipient,
            )
        except crud.InvalidTaskStateError as exc:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Task cannot be reviewed from its current status"
            ) from exc
        except crud.UnknownAssigneeError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "assigned_to must be an active employee of this firm",
            ) from exc
        session.flush()  # assigns the linked billing task's id, if any, before the response
        return status.HTTP_200_OK, TaskOut.from_task(updated).model_dump(mode="json")

    status_code, response_body = with_idempotency(
        session,
        actor,
        idempotency_key,
        f"POST /tasks/{task_id}/review",
        body.model_dump(mode="json"),
        _handler,
    )
    return JSONResponse(status_code=status_code, content=response_body)


@router.post("/{task_id}/issues", status_code=status.HTTP_201_CREATED)
def create_task_issue(
    task_id: UUID,
    body: IssueCreate,
    actor: ActiveProfileDep,
    session: SessionDep,
    idempotency_key: IdempotencyKeyHeader,
) -> JSONResponse:
    task = _get_task_or_404(session, actor, task_id)
    _require_assignee(session, actor, task, "raise an issue on this task")

    def _handler() -> tuple[int, dict[str, Any]]:
        try:
            issue = crud.create_issue(session, actor, task, body.description)
        except crud.InvalidTaskStateError as exc:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Cannot raise an issue on a task in its current status"
            ) from exc
        session.flush()  # assigns issue.id within the still-open transaction, before commit
        return status.HTTP_201_CREATED, IssueOut.from_issue(issue).model_dump(mode="json")

    status_code, response_body = with_idempotency(
        session,
        actor,
        idempotency_key,
        f"POST /tasks/{task_id}/issues",
        body.model_dump(mode="json"),
        _handler,
    )
    return JSONResponse(status_code=status_code, content=response_body)
