from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from hunt_board.auth.dependencies import require_admin
from hunt_board.core.observability import metrics
from hunt_board.db.models import Invitation, JobPosting, User
from hunt_board.db.session import get_db


router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/metrics", response_class=Response)
def prometheus_metrics(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    active = db.scalar(select(func.count(User.id)).where(User.is_active.is_(True))) or 0
    deactivated = db.scalar(select(func.count(User.id)).where(User.is_active.is_(False))) or 0
    invitations = {
        "created": db.scalar(select(func.count(Invitation.id))) or 0,
        "accepted": db.scalar(
            select(func.count(Invitation.id)).where(Invitation.status == "accepted")
        )
        or 0,
        "revoked": db.scalar(
            select(func.count(Invitation.id)).where(Invitation.status == "revoked")
        )
        or 0,
    }
    confidence = case(
        (JobPosting.classification_confidence >= 0.9, "high"),
        (JobPosting.classification_confidence >= 0.6, "medium"),
        else_="low",
    )
    classification_inventory = [
        (str(family), str(method), str(bucket), int(count))
        for family, method, bucket, count in db.execute(
            select(
                JobPosting.job_family_slug,
                JobPosting.classification_method,
                confidence,
                func.count(JobPosting.id),
            )
            .group_by(JobPosting.job_family_slug, JobPosting.classification_method, confidence)
        ).all()
    ]
    total_jobs = sum(item[3] for item in classification_inventory)
    other_jobs = sum(item[3] for item in classification_inventory if item[0] == "other")
    override_count = int(
        db.scalar(
            select(func.count(JobPosting.id)).where(JobPosting.classification_overridden_at.is_not(None))
        )
        or 0
    )
    return Response(
        metrics.render(
            active_profiles=int(active),
            deactivated_profiles=int(deactivated),
            invitations={key: int(value) for key, value in invitations.items()},
            classification_inventory=classification_inventory,
            classification_overrides=override_count,
            other_rate=(100 * other_jobs / total_jobs) if total_jobs else 0,
        ),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
