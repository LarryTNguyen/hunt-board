from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from hunt_board.api.schemas import JobPostingRead
from hunt_board.auth.single_user import get_single_user
from hunt_board.db.models import Application, ApplicationStatus, JobPosting, SavedJob, Source
from hunt_board.db.session import get_db
from hunt_board.jobs.service import get_job_with_user_state, job_read_payload

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobPostingRead])
def list_jobs(
    active: bool | None = Query(default=True),
    company: str | None = None,
    source_id: int | None = None,
    source_slug: str | None = None,
    ats: str | None = None,
    location: str | None = None,
    workplace_type: str | None = None,
    duplicate_status: str | None = None,
    include_duplicates: bool = False,
    min_score: float | None = Query(default=None, ge=0, le=100),
    search: str | None = None,
    title: str | None = None,
    saved: bool | None = None,
    application_status: str | None = None,
    remote_only: bool = False,
    sort_by: Literal[
        "ranking_score", "first_seen_at", "last_seen_at", "posted_at", "company_name", "title"
    ] = "ranking_score",
    sort_order: Literal["asc", "desc"] = "desc",
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[dict]:
    user = get_single_user(db, required=False)
    user_id = user.id if user else None
    saved_join = and_(SavedJob.job_posting_id == JobPosting.id, SavedJob.user_id == user_id)
    application_join = and_(Application.job_posting_id == JobPosting.id, Application.user_id == user_id)
    statement = (
        select(JobPosting, Source, SavedJob.id, Application.id, ApplicationStatus)
        .join(Source, Source.id == JobPosting.source_id)
        .outerjoin(SavedJob, saved_join)
        .outerjoin(Application, application_join)
        .outerjoin(ApplicationStatus, ApplicationStatus.id == Application.status_id)
    )

    if active is not None:
        statement = statement.where(JobPosting.active.is_(active))
    if company:
        statement = statement.where(JobPosting.company_name.ilike(f"%{company.strip()}%"))
    if source_id is not None:
        statement = statement.where(JobPosting.source_id == source_id)
    if source_slug:
        statement = statement.where(JobPosting.source_slug == source_slug.strip())
    if ats:
        statement = statement.where(Source.ats == ats.strip().lower())
    if location:
        statement = statement.where(JobPosting.location.ilike(f"%{location.strip()}%"))
    if workplace_type:
        statement = statement.where(JobPosting.workplace_type.ilike(f"%{workplace_type.strip()}%"))
    if duplicate_status:
        statement = statement.where(JobPosting.duplicate_status == duplicate_status)
    elif not include_duplicates:
        statement = statement.where(JobPosting.duplicate_status != "duplicate")
    if min_score is not None:
        statement = statement.where(JobPosting.ranking_score >= min_score)
    if search:
        pattern = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                JobPosting.title.ilike(pattern),
                JobPosting.company_name.ilike(pattern),
                JobPosting.location.ilike(pattern),
            )
        )
    if title:
        statement = statement.where(JobPosting.title.ilike(f"%{title.strip()}%"))
    if saved is True:
        statement = statement.where(SavedJob.id.is_not(None))
    elif saved is False:
        statement = statement.where(SavedJob.id.is_(None))
    if application_status:
        normalized_status = application_status.strip().lower()
        statement = statement.where(
            or_(
                func.lower(ApplicationStatus.slug) == normalized_status,
                func.lower(ApplicationStatus.name) == normalized_status,
            )
        )
    if remote_only:
        statement = statement.where(
            or_(JobPosting.workplace_type.ilike("%remote%"), JobPosting.location.ilike("%remote%"))
        )

    sort_columns = {
        "ranking_score": JobPosting.ranking_score,
        "first_seen_at": JobPosting.first_seen_at,
        "last_seen_at": JobPosting.last_seen_at,
        "posted_at": JobPosting.posted_at,
        "company_name": func.lower(JobPosting.company_name),
        "title": func.lower(JobPosting.title),
    }
    selected_sort = sort_columns[sort_by]
    selected_order = selected_sort.asc() if sort_order == "asc" else selected_sort.desc()
    statement = statement.order_by(
        JobPosting.active.desc(),
        case((JobPosting.duplicate_status == "duplicate", 1), else_=0).asc(),
        selected_order,
        JobPosting.id.desc(),
    ).offset(offset).limit(limit)

    return [job_read_payload(*row) for row in db.execute(statement).all()]


@router.get("/{job_id}", response_model=JobPostingRead)
def get_job(job_id: int, db: Session = Depends(get_db)) -> dict:
    user = get_single_user(db, required=False)
    row = get_job_with_user_state(db, job_id, user.id if user else None)
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job_read_payload(*row)
