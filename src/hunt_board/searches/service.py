from __future__ import annotations

from sqlalchemy import Select
from sqlalchemy.orm import Session

from hunt_board.db.models import JobPosting, SavedSearch
from hunt_board.jobs.query import (
    JobQueryFilters,
    apply_job_filters,
    apply_job_sort,
    count_jobs,
    job_row_statement,
)
from hunt_board.jobs.service import job_read_payload
from hunt_board.searches.schemas import SavedSearchFilters


def saved_filters(saved_search: SavedSearch) -> SavedSearchFilters:
    return SavedSearchFilters.model_validate(saved_search.filters_json or {})


def to_job_filters(filters: SavedSearchFilters) -> JobQueryFilters:
    return JobQueryFilters(
        active=filters.active,
        company=filters.company,
        source_slug=filters.source_slug,
        ats=filters.ats,
        location=filters.location,
        country=filters.country,
        workplace_type=filters.workplace_type,
        salary_known=filters.salary_known,
        duplicate_status=filters.duplicate_status,
        include_duplicates=filters.include_duplicates,
        min_score=filters.min_score,
        search=filters.q,
        saved=filters.saved,
        discarded=filters.discarded,
        application_status=filters.application_status,
        application_state=filters.application_state,
        remote_only=filters.remote_only,
        posted_within_days=filters.posted_within_days,
    )


def match_statement(
    db: Session,
    saved_search: SavedSearch,
    user_id: int,
    *,
    new_only: bool = False,
) -> tuple[Select, object | None, JobQueryFilters]:
    filters = to_job_filters(saved_filters(saved_search))
    statement, relevance = apply_job_filters(job_row_statement(user_id), db, filters)
    if new_only and saved_search.last_viewed_at is not None:
        statement = statement.where(JobPosting.first_seen_at > saved_search.last_viewed_at)
    return statement, relevance, filters


def saved_search_counts(db: Session, saved_search: SavedSearch, user_id: int) -> tuple[int, int]:
    statement, _, _ = match_statement(db, saved_search, user_id)
    match_count = count_jobs(db, statement)
    if saved_search.last_viewed_at is None:
        return match_count, match_count
    return match_count, count_jobs(
        db,
        statement.where(JobPosting.first_seen_at > saved_search.last_viewed_at),
    )


def saved_search_payload(
    db: Session,
    saved_search: SavedSearch,
    user_id: int,
    *,
    include_counts: bool = True,
    preview_limit: int = 0,
) -> dict:
    payload = {
        "id": saved_search.id,
        "name": saved_search.name,
        "description": saved_search.description,
        "filters": saved_filters(saved_search),
        "sort_by": saved_search.sort_by,
        "sort_order": saved_search.sort_order,
        "is_default": saved_search.is_default,
        "is_active": saved_search.is_active,
        "notify_on_new_matches": saved_search.notify_on_new_matches,
        "last_viewed_at": saved_search.last_viewed_at,
        "created_at": saved_search.created_at,
        "updated_at": saved_search.updated_at,
    }
    if include_counts:
        payload["match_count"], payload["new_since_review_count"] = saved_search_counts(
            db, saved_search, user_id
        )
    if preview_limit:
        statement, relevance, _ = match_statement(db, saved_search, user_id)
        statement = apply_job_sort(
            statement,
            saved_search.sort_by,
            saved_search.sort_order,
            relevance,
        ).limit(preview_limit)
        payload["preview_jobs"] = [
            job_read_payload(*row) for row in db.execute(statement).all()
        ]
    return payload
