from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from app import crud
from app.api.deps import ActiveProfileDep, SessionDep
from app.core.validation import LimitQuery, OffsetQuery

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
    offset: OffsetQuery = 0,
    limit: LimitQuery = 20,
    unread_only: Annotated[bool, Query()] = True,
) -> list[NotificationOut]:
    notifications = crud.list_notifications(session, actor, offset, limit, unread_only)
    return [NotificationOut.model_validate(n, from_attributes=True) for n in notifications]


@router.patch("/{notification_id}/read")
def mark_notification_read(
    notification_id: UUID, actor: ActiveProfileDep, session: SessionDep
) -> NotificationOut:
    notification = crud.get_notification(session, actor, notification_id)
    if notification is None:
        # 404, not 403 — recipient-only, same IDOR reasoning as every other resource here.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found")
    notification = crud.mark_notification_read(session, notification)
    return NotificationOut.model_validate(notification, from_attributes=True)
