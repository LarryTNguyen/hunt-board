from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from hunt_board.api.schemas import NotificationRead, NotificationReadAllResponse
from hunt_board.auth.dependencies import require_user
from hunt_board.db.models import DiscardedJob, Notification, User
from hunt_board.db.session import get_db

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationRead])
def list_notifications(
    unread: bool | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> list[Notification]:
    statement = (
        select(Notification)
        .outerjoin(
            DiscardedJob,
            (DiscardedJob.user_id == Notification.user_id)
            & (DiscardedJob.job_posting_id == Notification.job_posting_id),
        )
        .where(Notification.user_id == user.id, DiscardedJob.id.is_(None))
    )
    if unread is True:
        statement = statement.where(Notification.read_at.is_(None))
    elif unread is False:
        statement = statement.where(Notification.read_at.is_not(None))
    return list(
        db.scalars(
            statement.order_by(Notification.created_at.desc(), Notification.id.desc()).offset(offset).limit(limit)
        ).all()
    )


@router.patch("/{notification_id}/read", response_model=NotificationRead)
def mark_notification_read(
    notification_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> Notification:
    notification = db.scalar(
        select(Notification).where(Notification.id == notification_id, Notification.user_id == user.id)
    )
    if notification is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    if notification.read_at is None:
        notification.read_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(notification)
    return notification


@router.post("/read-all", response_model=NotificationReadAllResponse)
def mark_all_notifications_read(
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    result = db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(timezone.utc))
    )
    db.commit()
    return {"marked_read": result.rowcount or 0}
