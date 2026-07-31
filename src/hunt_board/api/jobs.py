from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from hunt_board.api.schemas import JobFeedRead, JobPostingRead
from hunt_board.auth.dependencies import optional_user
from hunt_board.db.models import User
from hunt_board.db.session import get_db
from hunt_board.jobs.query import (
    JobQueryFilters,
    SortBy,
    SortOrder,
    apply_job_filters,
    apply_job_sort,
    count_jobs,
    feed_facets,
    job_row_statement,
)
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
    country: str | None = None,
    workplace_type: str | None = None,
    salary_known: bool | None = None,
    duplicate_status: str | None = None,
    include_duplicates: bool = False,
    min_score: float | None = Query(default=None, ge=0, le=100),
    search: str | None = Query(default=None, max_length=500),
    title: str | None = None,
    saved: bool | None = None,
    discarded: bool = False,
    application_status: str | None = None,
    application_state: Literal["none", "tracked", "any"] = "any",
    remote_only: bool = False,
    posted_within_days: int | None = Query(default=None, ge=1, le=3650),
    sort_by: SortBy = "ranking_score",
    sort_order: SortOrder = "desc",
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User | None = Depends(optional_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    if user is None and (saved is not None or discarded or application_status):
        raise HTTPException(status_code=401, detail="Authentication is required for private job filters")
    filters = JobQueryFilters(
        active=active,
        company=company,
        source_id=source_id,
        source_slug=source_slug,
        ats=ats,
        location=location,
        country=country,
        workplace_type=workplace_type,
        salary_known=salary_known,
        duplicate_status=duplicate_status,
        include_duplicates=include_duplicates,
        min_score=min_score,
        search=search,
        title=title,
        saved=saved,
        discarded=discarded,
        application_status=application_status,
        application_state=application_state,
        remote_only=remote_only,
        posted_within_days=posted_within_days,
    )
    statement, relevance = apply_job_filters(job_row_statement(user.id if user else None), db, filters)
    statement = apply_job_sort(statement, sort_by, sort_order, relevance).offset(offset).limit(limit)
    return [job_read_payload(*row) for row in db.execute(statement).all()]


@router.get("/feed", response_model=JobFeedRead)
def discovery_feed(
    q: str | None = Query(default=None, max_length=500),
    active: bool | None = Query(default=True),
    company: str | None = None,
    source_slug: str | None = None,
    ats: str | None = None,
    location: str | None = None,
    country: str | None = None,
    workplace_type: str | None = None,
    salary_known: bool | None = None,
    saved: bool | None = None,
    discarded: bool = False,
    application_status: str | None = None,
    application_state: Literal["none", "tracked", "any"] = "none",
    remote_only: bool = False,
    min_score: float | None = Query(default=None, ge=0, le=100),
    posted_within_days: int | None = Query(default=None, ge=1, le=3650),
    sort_by: SortBy = "ranking_score",
    sort_order: SortOrder = "desc",
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    include_duplicates: bool = False,
    user: User | None = Depends(optional_user),
    db: Session = Depends(get_db),
) -> dict:
    if user is None and (saved is not None or discarded or application_status):
        raise HTTPException(status_code=401, detail="Authentication is required for private job filters")
    user_id = user.id if user else None
    filters = JobQueryFilters(
        active=active,
        company=company,
        source_slug=source_slug,
        ats=ats,
        location=location,
        country=country,
        workplace_type=workplace_type,
        salary_known=salary_known,
        saved=saved,
        discarded=discarded,
        application_status=application_status,
        application_state=application_state,
        remote_only=remote_only,
        min_score=min_score,
        posted_within_days=posted_within_days,
        search=q,
        include_duplicates=include_duplicates,
    )
    base_statement, relevance = apply_job_filters(job_row_statement(user_id), db, filters)
    total = count_jobs(db, base_statement)
    statement = apply_job_sort(base_statement, sort_by, sort_order, relevance).offset(offset).limit(limit)
    items = [job_read_payload(*row) for row in db.execute(statement).all()]
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(items) < total,
        "generated_at": datetime.now(timezone.utc),
        "facets": feed_facets(db, user_id, filters),
    }


@router.get("/{job_id}", response_model=JobPostingRead)
def get_job(
    job_id: int,
    user: User | None = Depends(optional_user),
    db: Session = Depends(get_db),
) -> dict:
    row = get_job_with_user_state(db, job_id, user.id if user else None)
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job_read_payload(*row)
