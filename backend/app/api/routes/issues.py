from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator

from app import crud
from app.api.deps import IdempotencyKeyHeader, RequireOwnerDep, SessionDep
from app.api.routes.tasks import IssueOut
from app.core.idempotency import with_idempotency
from app.core.validation import NoNulStr

router = APIRouter(prefix="/issues", tags=["issues"])


class IssueResolveRequest(BaseModel):
    resolution_type: Literal["clarified", "deadline_adjusted", "reassigned"]
    resolution_notes: NoNulStr = Field(min_length=1, max_length=2000)
    new_deadline: datetime | None = None
    assigned_to: UUID | None = None
    # PRD §3.3: an issue-triggered reassignment must surface remaining-work same as a review-
    # triggered one — required below, checked directly against the PRD 2026-09-04, not assumed.
    remaining_work_description: NoNulStr | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _validate_resolution_fields(self) -> "IssueResolveRequest":
        # Same "Validate Combinations" reasoning as TaskReviewCreate (routes/tasks.py).
        if self.resolution_type == "deadline_adjusted" and self.new_deadline is None:
            raise ValueError("new_deadline is required for resolution_type=deadline_adjusted")
        if self.resolution_type != "deadline_adjusted" and self.new_deadline is not None:
            raise ValueError("new_deadline is only valid for resolution_type=deadline_adjusted")
        if self.resolution_type != "reassigned" and self.assigned_to is not None:
            raise ValueError("assigned_to is only valid for resolution_type=reassigned")
        if self.resolution_type == "reassigned" and not self.remaining_work_description:
            raise ValueError(
                "remaining_work_description is required for resolution_type=reassigned"
            )
        if self.resolution_type != "reassigned" and self.remaining_work_description:
            raise ValueError(
                "remaining_work_description is only valid for resolution_type=reassigned"
            )
        return self


@router.post("/{issue_id}/resolve")
def resolve_issue(
    issue_id: UUID,
    body: IssueResolveRequest,
    actor: RequireOwnerDep,
    session: SessionDep,
    idempotency_key: IdempotencyKeyHeader,
) -> JSONResponse:
    # RLS already scopes this select to the caller's own firm (app.current_tenant); role is
    # Owner-only via RequireOwnerDep, so no separate "visible to" check is needed the way tasks'
    # employee-scoped get_task needs one — every issue in the firm is an Owner's to resolve.
    issue = crud.get_issue(session, issue_id)
    if issue is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Issue not found")

    def _handler() -> tuple[int, dict[str, Any]]:
        try:
            resolved = crud.resolve_issue(
                session,
                actor,
                issue,
                body.resolution_type,
                body.resolution_notes,
                body.remaining_work_description,
                body.new_deadline,
                body.assigned_to,
            )
        except crud.InvalidIssueStateError as exc:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Issue has already been resolved"
            ) from exc
        except crud.UnknownAssigneeError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "assigned_to must be an active employee of this firm",
            ) from exc
        return status.HTTP_200_OK, IssueOut.from_issue(resolved).model_dump(mode="json")

    status_code, response_body = with_idempotency(
        session,
        actor,
        idempotency_key,
        f"POST /issues/{issue_id}/resolve",
        body.model_dump(mode="json"),
        _handler,
    )
    return JSONResponse(status_code=status_code, content=response_body)
