from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from sqlalchemy import Select, and_, case, func, literal, literal_column, or_, select
from sqlalchemy.orm import Session

from hunt_board.db.models import (
    Application,
    ApplicationStatus,
    DiscardedJob,
    JobPosting,
    SavedJob,
    Source,
)


SortBy = Literal[
    "relevance",
    "ranking_score",
    "first_seen_at",
    "last_seen_at",
    "posted_at",
    "company_name",
    "title",
]
SortOrder = Literal["asc", "desc"]


@dataclass(frozen=True)
class JobQueryFilters:
    active: bool | None = True
    company: str | None = None
    source_id: int | None = None
    source_slug: str | None = None
    ats: str | None = None
    location: str | None = None
    country: str | None = None
    workplace_type: str | None = None
    salary_known: bool | None = None
    duplicate_status: str | None = None
    include_duplicates: bool = False
    min_score: float | None = None
    search: str | None = None
    title: str | None = None
    saved: bool | None = None
    discarded: bool | None = False
    application_status: str | None = None
    application_state: Literal["none", "tracked", "any"] = "any"
    remote_only: bool = False
    posted_within_days: int | None = None


def user_state_statement(user_id: int | None, *columns: Any) -> Select:
    saved_join = and_(SavedJob.job_posting_id == JobPosting.id, SavedJob.user_id == user_id)
    discarded_join = and_(DiscardedJob.job_posting_id == JobPosting.id, DiscardedJob.user_id == user_id)
    latest_application_id = (
        select(func.max(Application.id))
        .where(
            Application.job_posting_id == JobPosting.id,
            Application.user_id == user_id,
        )
        .correlate(JobPosting)
        .scalar_subquery()
    )
    application_join = Application.id == latest_application_id
    return (
        select(*columns)
        .select_from(JobPosting)
        .join(Source, Source.id == JobPosting.source_id)
        .outerjoin(SavedJob, saved_join)
        .outerjoin(DiscardedJob, discarded_join)
        .outerjoin(Application, application_join)
        .outerjoin(ApplicationStatus, ApplicationStatus.id == Application.status_id)
    )


def job_row_statement(user_id: int | None) -> Select:
    return user_state_statement(
        user_id,
        JobPosting,
        Source,
        SavedJob.id,
        DiscardedJob.id,
        DiscardedJob.created_at,
        Application.id,
        ApplicationStatus,
    )


def apply_job_filters(
    statement: Select,
    db: Session,
    filters: JobQueryFilters,
    *,
    exclude: frozenset[str] = frozenset(),
) -> tuple[Select, Any | None]:
    if "active" not in exclude and filters.active is not None:
        statement = statement.where(JobPosting.active.is_(filters.active))
    if "company" not in exclude and filters.company:
        statement = statement.where(JobPosting.company_name.ilike(f"%{filters.company.strip()}%"))
    if "source_id" not in exclude and filters.source_id is not None:
        statement = statement.where(JobPosting.source_id == filters.source_id)
    if "source_slug" not in exclude and filters.source_slug:
        statement = statement.where(JobPosting.source_slug == filters.source_slug.strip())
    if "ats" not in exclude and filters.ats:
        statement = statement.where(Source.ats == filters.ats.strip().lower())
    if "location" not in exclude and filters.location:
        statement = statement.where(JobPosting.location.ilike(f"%{filters.location.strip()}%"))
    if "country" not in exclude and filters.country:
        normalized_country = filters.country.strip()
        if len(normalized_country) == 2:
            statement = statement.where(JobPosting.location_country_code == normalized_country.upper())
        else:
            statement = statement.where(JobPosting.location_country.ilike(f"%{normalized_country}%"))
    if "workplace_type" not in exclude and filters.workplace_type:
        statement = statement.where(JobPosting.workplace_type.ilike(f"%{filters.workplace_type.strip()}%"))
    if "salary_known" not in exclude:
        if filters.salary_known is True:
            statement = statement.where(or_(JobPosting.salary_min.is_not(None), JobPosting.salary_max.is_not(None)))
        elif filters.salary_known is False:
            statement = statement.where(JobPosting.salary_min.is_(None), JobPosting.salary_max.is_(None))
    if "duplicate_status" not in exclude and filters.duplicate_status:
        statement = statement.where(JobPosting.duplicate_status == filters.duplicate_status)
    elif "include_duplicates" not in exclude and not filters.include_duplicates:
        statement = statement.where(JobPosting.duplicate_status != "duplicate")
    if "min_score" not in exclude and filters.min_score is not None:
        statement = statement.where(JobPosting.ranking_score >= filters.min_score)
    if "title" not in exclude and filters.title:
        statement = statement.where(JobPosting.title.ilike(f"%{filters.title.strip()}%"))
    if "saved" not in exclude:
        if filters.saved is True:
            statement = statement.where(SavedJob.id.is_not(None))
        elif filters.saved is False:
            statement = statement.where(SavedJob.id.is_(None))
    if "discarded" not in exclude:
        if filters.discarded is True:
            statement = statement.where(DiscardedJob.id.is_not(None))
        elif filters.discarded is False:
            statement = statement.where(DiscardedJob.id.is_(None))
    if "application_status" not in exclude and filters.application_status:
        normalized_status = filters.application_status.strip().lower()
        statement = statement.where(
            or_(
                func.lower(ApplicationStatus.slug) == normalized_status,
                func.lower(ApplicationStatus.name) == normalized_status,
            )
        )
    if "application_state" not in exclude:
        if filters.application_state == "none":
            statement = statement.where(Application.id.is_(None))
        elif filters.application_state == "tracked":
            statement = statement.where(Application.id.is_not(None))
    if "remote_only" not in exclude and filters.remote_only:
        statement = statement.where(
            or_(JobPosting.workplace_type.ilike("%remote%"), JobPosting.location.ilike("%remote%"))
        )
    if "posted_within_days" not in exclude and filters.posted_within_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=filters.posted_within_days)
        statement = statement.where(func.coalesce(JobPosting.posted_at, JobPosting.first_seen_at) >= cutoff)

    relevance = None
    normalized_search = filters.search.strip() if filters.search else ""
    if "search" not in exclude and normalized_search:
        if db.get_bind().dialect.name == "postgresql":
            query = func.websearch_to_tsquery("english", normalized_search)
            vector = literal_column("job_postings.search_vector")
            statement = statement.where(vector.op("@@")(query))
            relevance = func.ts_rank_cd(vector, query)
        else:
            pattern = f"%{normalized_search}%"
            title_match = JobPosting.title.ilike(pattern)
            company_match = JobPosting.company_name.ilike(pattern)
            location_match = or_(JobPosting.location.ilike(pattern), JobPosting.department.ilike(pattern))
            description_match = JobPosting.description_text.ilike(pattern)
            statement = statement.where(or_(title_match, company_match, location_match, description_match))
            relevance = (
                case((title_match, 4), else_=0)
                + case((company_match, 3), else_=0)
                + case((location_match, 2), else_=0)
                + case((description_match, 1), else_=0)
            )
    return statement, relevance


def apply_job_sort(statement: Select, sort_by: SortBy, sort_order: SortOrder, relevance: Any | None) -> Select:
    sort_columns = {
        "ranking_score": JobPosting.ranking_score,
        "first_seen_at": JobPosting.first_seen_at,
        "last_seen_at": JobPosting.last_seen_at,
        "posted_at": JobPosting.posted_at,
        "company_name": func.lower(JobPosting.company_name),
        "title": func.lower(JobPosting.title),
    }
    selected_sort = relevance if sort_by == "relevance" and relevance is not None else sort_columns.get(
        sort_by, JobPosting.ranking_score
    )
    selected_order = selected_sort.asc() if sort_order == "asc" else selected_sort.desc()
    return statement.order_by(
        JobPosting.active.desc(),
        case((JobPosting.duplicate_status == "duplicate", 1), else_=0).asc(),
        selected_order,
        JobPosting.id.desc(),
    )


def count_jobs(db: Session, statement: Select) -> int:
    return int(db.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0)


def feed_facets(db: Session, user_id: int | None, filters: JobQueryFilters) -> dict[str, list[dict]]:
    return {
        "ats": _facet(db, user_id, filters, "ats"),
        "sources": _facet(db, user_id, filters, "source_slug"),
        "countries": _facet(db, user_id, filters, "country"),
        "workplace_types": _facet(db, user_id, filters, "workplace_type"),
        "salary_known": _facet(db, user_id, filters, "salary_known"),
    }


def _facet(db: Session, user_id: int | None, filters: JobQueryFilters, key: str) -> list[dict]:
    if key == "ats":
        value, facet_label = Source.ats, Source.ats
    elif key == "source_slug":
        value, facet_label = Source.slug, Source.company_name
    elif key == "country":
        value = JobPosting.location_country_code
        facet_label = func.coalesce(JobPosting.location_country, JobPosting.location_country_code)
    elif key == "workplace_type":
        value, facet_label = JobPosting.workplace_type, JobPosting.workplace_type
    else:
        known = or_(JobPosting.salary_min.is_not(None), JobPosting.salary_max.is_not(None))
        value = case((known, literal("true")), else_=literal("false"))
        facet_label = case((known, literal("Salary listed")), else_=literal("Salary not listed"))

    count_column = func.count(JobPosting.id).label("facet_count")
    statement = user_state_statement(user_id, value.label("facet_value"), facet_label.label("facet_label"), count_column)
    statement, _ = apply_job_filters(statement, db, filters, exclude=frozenset({key}))
    if key != "salary_known":
        statement = statement.where(value.is_not(None))
    statement = statement.group_by(value, facet_label).order_by(count_column.desc(), facet_label.asc())
    rows = db.execute(statement).all()
    return [
        {
            "value": str(row.facet_value),
            "label": _display_facet_label(key, str(row.facet_label)),
            "count": int(row.facet_count),
        }
        for row in rows
        if row.facet_value not in (None, "")
    ]


def _display_facet_label(key: str, value: str) -> str:
    if key == "ats":
        return value.replace("_", " ").title()
    if key == "workplace_type":
        return value.replace("_", " ").replace("-", " ").title()
    return value
