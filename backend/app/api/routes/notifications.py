from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from app import crud
from app.api.deps import ActiveProfileDep, SessionDep

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    id: UUID
    type: str
    task_id: UUID | None
    issue_id: UUID | None
    is_read: bool
    created_at: datetime


@router.get("")
def list_notifications(
    actor: ActiveProfileDep,
    session: SessionDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    unread_only: Annotated[bool, Query()] = True,
) -> list[NotificationOut]:
    notifications = crud.list_notifications(session, actor, offset, limit, unread_only)
    return [
        NotificationOut(
            id=n.id,
            type=n.type,
            task_id=n.task_id,
            issue_id=n.issue_id,
            is_read=n.is_read,
            created_at=n.created_at,
        )
        for n in notifications
    ]


@router.patch("/{notification_id}/read")
def mark_notification_read(
    notification_id: UUID, actor: ActiveProfileDep, session: SessionDep
) -> NotificationOut:
    notification = crud.get_notification(session, actor, notification_id)
    if notification is None:
        # 404, not 403 — recipient-only, same IDOR reasoning as every other resource here.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found")
    notification = crud.mark_notification_read(session, notification)
    return NotificationOut(
        id=notification.id,
        type=notification.type,
        task_id=notification.task_id,
        issue_id=notification.issue_id,
        is_read=notification.is_read,
        created_at=notification.created_at,
    )
