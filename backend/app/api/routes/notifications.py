from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlmodel import Session

from app import crud
from app.api.deps import ActiveProfileDep, SessionDep
from app.core.validation import LimitQuery, OffsetQuery
from app.models import Notification, Profile

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    id: UUID
    type: str
    task_id: UUID | None
    issue_id: UUID | None
    task_title: str | None
    is_read: bool
    created_at: datetime


def _to_notification_out(
    session: Session, actor: Profile, n: Notification, task_title: str | None
) -> NotificationOut:
    return NotificationOut(
        id=n.id,
        type=n.type,
        task_id=n.task_id,
        issue_id=n.issue_id,
        task_title=task_title,
        is_read=n.is_read,
        created_at=n.created_at,
    )


@router.get("")
def list_notifications(
    actor: ActiveProfileDep,
    session: SessionDep,
    offset: OffsetQuery = 0,
    limit: LimitQuery = 20,
    unread_only: Annotated[bool, Query()] = True,
) -> list[NotificationOut]:
    notifications = crud.list_notifications(session, actor, offset, limit, unread_only)
    task_ids = [n.task_id for n in notifications if n.task_id is not None]
    titles = crud.get_task_titles(session, actor, task_ids)
    return [
        _to_notification_out(session, actor, n, titles.get(n.task_id) if n.task_id else None)
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
    # Title lookup BEFORE mark_notification_read, not after: that call commits, which ends the
    # transaction the RLS tenant context (`set_config(..., true)`) lives in, so a query after it
    # runs with no tenant context — a 500 (uuid-cast DataError) or a silently null title. Same bug
    # class as crud.py's module docstring; found 2026-09-19 (test_notifications_real_db.py).
    task_ids = [notification.task_id] if notification.task_id else []
    titles = crud.get_task_titles(session, actor, task_ids)
    notification = crud.mark_notification_read(session, notification)
    task_title = titles.get(notification.task_id) if notification.task_id else None
    return _to_notification_out(session, actor, notification, task_title)
