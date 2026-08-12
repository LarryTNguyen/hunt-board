from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from hunt_board.api.schemas import JobFeedRead, JobPostingRead, PublicJobRead
from hunt_board.auth.dependencies import optional_user, require_user
from hunt_board.db.models import JobPosting, User, UserJobState, UserPreference
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
from hunt_board.jobs.relaxation import execute_with_relaxation

router = APIRouter(prefix="/jobs", tags=["jobs"])
public_router = APIRouter(prefix="/public", tags=["public catalog"])


@router.get("", response_model=list[JobPostingRead | PublicJobRead])
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
    if user is None:
        rows = db.execute(
            apply_job_sort(job_row_statement(None), "first_seen_at", "desc", None, filters).limit(min(limit, 30))
        ).all()
        return [_public_payload(row[0]) for row in rows]
    statement, relevance = apply_job_filters(job_row_statement(user.id if user else None), db, filters)
    statement = apply_job_sort(statement, sort_by, sort_order, relevance, filters).offset(offset).limit(limit)
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
    job_families: list[str] = Query(default=[]),
    related_job_families: list[str] = Query(default=[]),
    desired_titles: list[str] = Query(default=[]),
    include_keywords: list[str] = Query(default=[]),
    exclude_keywords: list[str] = Query(default=[]),
    countries: list[str] = Query(default=[]),
    excluded_countries: list[str] = Query(default=[]),
    workplace_types: list[str] = Query(default=[]),
    employment_types: list[str] = Query(default=[]),
    experience_levels: list[str] = Query(default=[]),
    sponsorship_required: bool | None = None,
    min_salary: float | None = Query(default=None, ge=0),
    excluded_companies: list[str] = Query(default=[]),
    relax: bool = False,
    minimum_results: int = Query(default=10, ge=1, le=100),
    use_preferences: bool = False,
    user: User | None = Depends(optional_user),
    db: Session = Depends(get_db),
) -> dict:
    if user is None and (saved is not None or discarded or application_status):
        raise HTTPException(status_code=401, detail="Authentication is required for private job filters")
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication is required for the full discovery feed")
    user_id = user.id
    preference = db.scalar(select(UserPreference).where(UserPreference.user_id == user.id)) if use_preferences else None
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
        job_families=tuple(job_families or (preference.selected_job_families if preference else [])),
        related_job_families=tuple(related_job_families or (preference.related_job_families if preference else [])),
        desired_titles=tuple(desired_titles or (preference.desired_titles if preference else [])),
        include_keywords=tuple(include_keywords or (preference.include_keywords if preference else [])),
        exclude_keywords=tuple(exclude_keywords or (preference.exclude_keywords if preference else [])),
        countries=tuple(countries or (preference.preferred_countries if preference else [])),
        excluded_countries=tuple(excluded_countries or (preference.excluded_countries if preference else [])),
        workplace_types=tuple(workplace_types or (preference.workplace_preferences if preference else [])),
        employment_types=tuple(employment_types or (preference.employment_types if preference else [])),
        experience_levels=tuple(experience_levels),
        sponsorship_required=sponsorship_required if sponsorship_required is not None else (preference.sponsorship_required if preference else None),
        min_salary=min_salary if min_salary is not None else (float(preference.minimum_salary) if preference and preference.minimum_salary is not None else None),
        excluded_companies=tuple(excluded_companies or (preference.excluded_companies if preference else [])),
    )
    if relax:
        execution = execute_with_relaxation(db, user_id, filters, minimum_results=minimum_results)
        base_statement, relevance = execution.final_statement, execution.relevance
        strict_total, total = execution.strict_total, execution.final_total
        final_filters = execution.final_filters
        relaxed_filters = list(execution.relaxed_filters)
    else:
        base_statement, relevance = apply_job_filters(job_row_statement(user_id), db, filters)
        total = strict_total = count_jobs(db, base_statement)
        final_filters = filters
        relaxed_filters = []
    strict_ids = set(
        db.scalars(
            apply_job_filters(job_row_statement(user_id), db, filters)[0]
            .with_only_columns(JobPosting.id)
            .order_by(None)
        ).all()
    ) if relaxed_filters else set()
    statement = apply_job_sort(base_statement, sort_by, sort_order, relevance, final_filters).offset(offset).limit(limit)
    items = []
    for row in db.execute(statement).all():
        payload = job_read_payload(*row)
        if relaxed_filters and payload["id"] not in strict_ids:
            payload["match_type"] = "relaxed"
            payload["relaxed_filters"] = relaxed_filters
        items.append(payload)
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(items) < total,
        "generated_at": datetime.now(timezone.utc),
        "facets": feed_facets(db, user_id, filters),
        "strict_total": strict_total,
        "relaxed_total": max(total - strict_total, 0),
        "relaxed_filters": relaxed_filters,
        "relaxation_notice": (
            f"Broadened results by relaxing: {', '.join(relaxed_filters)}. Exclusions remain enforced."
            if relaxed_filters else None
        ),
    }


def _public_payload(job) -> dict:
    return {
        "id": job.id,
        "title": job.title,
        "company_name": job.company_name,
        "location": job.location,
        "workplace_type": job.workplace_type,
        "employment_type": job.employment_type,
        "job_family_slug": job.job_family_slug,
        "salary_min": job.salary_min,
        "salary_max": job.salary_max,
        "salary_currency": job.salary_currency,
        "salary_interval": job.salary_interval,
        "apply_url": job.apply_url,
        "posted_at": job.posted_at,
    }


@public_router.get("/jobs", response_model=list[PublicJobRead])
def public_catalog(
    limit: int = Query(default=30, ge=1, le=50),
    db: Session = Depends(get_db),
) -> list[dict]:
    filters = JobQueryFilters(active=True, include_duplicates=False, discarded=None, application_state="any")
    statement, relevance = apply_job_filters(job_row_statement(None), db, filters)
    rows = db.execute(apply_job_sort(statement, "first_seen_at", "desc", relevance, filters).limit(limit)).all()
    return [_public_payload(row[0]) for row in rows]


@router.get("/{job_id}", response_model=JobPostingRead | PublicJobRead)
def get_job(
    job_id: int,
    user: User | None = Depends(optional_user),
    db: Session = Depends(get_db),
) -> dict:
    row = get_job_with_user_state(db, job_id, user.id if user else None)
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication is required for full job details")
    return job_read_payload(*row)


@router.post("/{job_id}/seen", response_model=JobPostingRead)
def mark_job_seen(
    job_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    if db.get(JobPosting, job_id) is None:
        raise HTTPException(status_code=404, detail="Job not found")
    state = db.scalar(
        select(UserJobState).where(
            UserJobState.user_id == user.id,
            UserJobState.job_posting_id == job_id,
        )
    )
    if state is None:
        state = UserJobState(
            user_id=user.id,
            job_posting_id=job_id,
            seen_at=datetime.now(timezone.utc),
        )
        db.add(state)
    elif state.seen_at is None:
        state.seen_at = datetime.now(timezone.utc)
    db.commit()
    row = get_job_with_user_state(db, job_id, user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job_read_payload(*row)
