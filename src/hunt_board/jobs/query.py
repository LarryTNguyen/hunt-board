from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from time import perf_counter
from typing import Any, Literal

from sqlalchemy import Select, String, and_, case, cast, func, literal, literal_column, not_, or_, select
from sqlalchemy.orm import Session

from hunt_board.db.models import (
    Application,
    ApplicationStatus,
    DiscardedJob,
    JobPosting,
    SavedJob,
    Source,
    UserJobState,
)
from hunt_board.core.observability import trace_span


logger = logging.getLogger("hunt_board")


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
    job_families: tuple[str, ...] = ()
    related_job_families: tuple[str, ...] = ()
    desired_titles: tuple[str, ...] = ()
    include_keywords: tuple[str, ...] = ()
    exclude_keywords: tuple[str, ...] = ()
    countries: tuple[str, ...] = ()
    excluded_countries: tuple[str, ...] = ()
    workplace_types: tuple[str, ...] = ()
    employment_types: tuple[str, ...] = ()
    experience_levels: tuple[str, ...] = ()
    sponsorship_required: bool | None = None
    min_salary: float | None = None
    excluded_companies: tuple[str, ...] = ()


def user_state_statement(user_id: int | None, *columns: Any) -> Select:
    saved_join = and_(SavedJob.job_posting_id == JobPosting.id, SavedJob.user_id == user_id)
    discarded_join = and_(DiscardedJob.job_posting_id == JobPosting.id, DiscardedJob.user_id == user_id)
    combined_state_join = and_(UserJobState.job_posting_id == JobPosting.id, UserJobState.user_id == user_id)
    latest_application_id = (
        select(func.max(Application.id))
        .where(
            Application.job_posting_id == JobPosting.id,
            Application.user_id == user_id,
            Application.deleted_at.is_(None),
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
        .outerjoin(UserJobState, combined_state_join)
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
        UserJobState.seen_at,
    )


def apply_job_filters(
    statement: Select,
    db: Session,
    filters: JobQueryFilters,
    *,
    exclude: frozenset[str] = frozenset(),
) -> tuple[Select, Any | None]:
    started = perf_counter()
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
        statement = statement.where(JobPosting.posted_at >= cutoff)
    if "job_families" not in exclude and filters.job_families:
        statement = statement.where(JobPosting.job_family_slug.in_(filters.job_families))
    if "desired_titles" not in exclude and filters.desired_titles:
        statement = statement.where(
            or_(*(JobPosting.title.ilike(f"%{title.strip()}%") for title in filters.desired_titles))
        )
    if "include_keywords" not in exclude and filters.include_keywords:
        searchable = func.coalesce(JobPosting.title, "") + " " + func.coalesce(JobPosting.description_text, "")
        statement = statement.where(
            or_(*(searchable.ilike(f"%{keyword.strip()}%") for keyword in filters.include_keywords))
        )
    if filters.exclude_keywords:
        searchable = func.coalesce(JobPosting.title, "") + " " + func.coalesce(JobPosting.description_text, "")
        specific_includes = tuple(
            keyword for keyword in filters.include_keywords if len(keyword.strip().split()) > 1
        )
        statement = statement.where(
            and_(
                *(
                    or_(
                        not_(searchable.ilike(f"%{keyword.strip()}%")),
                        *(
                            JobPosting.title.ilike(f"%{include.strip()}%")
                            for include in specific_includes
                        ),
                    )
                    for keyword in filters.exclude_keywords
                )
            )
        )
    if filters.excluded_companies:
        statement = statement.where(
            and_(*(not_(JobPosting.company_name.ilike(f"%{company.strip()}%")) for company in filters.excluded_companies))
        )
    if "countries" not in exclude and filters.countries:
        locations_text = cast(JobPosting.locations_json, String)
        country_checks = []
        for country in filters.countries:
            normalized = country.strip()
            country_checks.extend(
                [
                    JobPosting.location_country_code == normalized.upper(),
                    JobPosting.location_country.ilike(f"%{normalized}%"),
                    locations_text.ilike(f"%{normalized}%"),
                ]
            )
        statement = statement.where(or_(*country_checks))
    if filters.excluded_countries:
        locations_text = cast(JobPosting.locations_json, String)
        for country in filters.excluded_countries:
            normalized = country.strip()
            statement = statement.where(
                not_(
                    or_(
                        JobPosting.location_country_code == normalized.upper(),
                        JobPosting.location_country.ilike(f"%{normalized}%"),
                        locations_text.ilike(f"%{normalized}%"),
                    )
                )
            )
    if "workplace_types" not in exclude and filters.workplace_types:
        statement = statement.where(
            or_(*(JobPosting.workplace_type.ilike(f"%{value.strip()}%") for value in filters.workplace_types))
        )
    if filters.employment_types:
        statement = statement.where(
            or_(*(JobPosting.employment_type.ilike(f"%{value.strip()}%") for value in filters.employment_types))
        )
    if "experience_levels" not in exclude and filters.experience_levels:
        level_terms = {
            "internship": ("intern", "internship"),
            "co-op": ("co-op", "coop"),
            "new-grad": ("new grad", "graduate"),
            "entry-level": ("entry", "junior", "associate"),
            "experienced": ("senior", "staff", "principal", "lead", "manager", "director"),
        }
        terms = tuple(term for level in filters.experience_levels for term in level_terms.get(level, (level,)))
        statement = statement.where(or_(*(JobPosting.title.ilike(f"%{term}%") for term in terms)))
    if filters.sponsorship_required is True:
        statement = statement.where(JobPosting.sponsorship_status == "available")
    elif filters.sponsorship_required is False:
        statement = statement.where(JobPosting.sponsorship_status != "required")
    if "min_salary" not in exclude and filters.min_salary is not None:
        known_salary = or_(JobPosting.salary_min.is_not(None), JobPosting.salary_max.is_not(None))
        salary_meets = func.coalesce(JobPosting.salary_max, JobPosting.salary_min) >= filters.min_salary
        statement = statement.where(or_(not_(known_salary), salary_meets))

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
    logger.info(
        "job_query.construction",
        extra={
            "event_name": "job_query.construction",
            "event_data": {
                "filter_fields": sorted(
                    field
                    for field, value in vars(filters).items()
                    if value not in (None, False, "", (), [])
                ),
                "duration_ms": round((perf_counter() - started) * 1000, 3),
            },
        },
    )
    return statement, relevance


def apply_job_sort(
    statement: Select,
    sort_by: SortBy,
    sort_order: SortOrder,
    relevance: Any | None,
    filters: JobQueryFilters | None = None,
) -> Select:
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
    salary_order = []
    if filters is not None and filters.min_salary is not None:
        salary_order = [
            case(
                (func.coalesce(JobPosting.salary_max, JobPosting.salary_min) >= filters.min_salary, 0),
                (JobPosting.salary_min.is_(None) & JobPosting.salary_max.is_(None), 1),
                else_=2,
            ).asc()
        ]
    return statement.order_by(
        JobPosting.active.desc(),
        case((JobPosting.duplicate_status == "duplicate", 1), else_=0).asc(),
        *salary_order,
        selected_order,
        JobPosting.id.desc(),
    )


def count_jobs(db: Session, statement: Select) -> int:
    with trace_span(logger, "job_query.database", operation="count"):
        return int(db.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0)


def feed_facets(db: Session, user_id: int | None, filters: JobQueryFilters) -> dict[str, list[dict]]:
    return {
        "ats": _facet(db, user_id, filters, "ats"),
        "sources": _facet(db, user_id, filters, "source_slug"),
        "countries": _facet(db, user_id, filters, "country"),
        "workplace_types": _facet(db, user_id, filters, "workplace_type"),
        "salary_known": _facet(db, user_id, filters, "salary_known"),
        "job_families": _facet(db, user_id, filters, "job_families"),
        "employment_types": _facet(db, user_id, filters, "employment_types"),
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
    elif key == "job_families":
        value, facet_label = JobPosting.job_family_slug, JobPosting.job_family_slug
    elif key == "employment_types":
        value, facet_label = JobPosting.employment_type, JobPosting.employment_type
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
    with trace_span(logger, "job_query.database", operation="facet", facet=key):
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
    if key == "job_families":
        return value.replace("-", " ").title()
    return value
