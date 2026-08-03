from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from hunt_board.matching.ranking import ROLE_GROUPS
from hunt_board.jobs.classification import JOB_FAMILY_SLUGS


class SourceSummaryRead(BaseModel):
    id: int
    slug: str
    name: str
    ats: str
    company_name: str
    company_logo_url: str | None


class ApplicationStatusRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    sort_order: int
    is_terminal: bool
    standard_category: str
    is_custom: bool = False


class JobLocationRead(BaseModel):
    display: str
    country_code: str | None = None
    country: str | None = None
    is_primary: bool = False


class JobPostingRead(BaseModel):
    id: int
    source_id: int
    source_slug: str
    source: SourceSummaryRead | None = None
    company_name: str
    external_job_id: str | None
    title: str
    location: str | None
    location_country_code: str | None
    location_country: str | None
    locations: list[JobLocationRead] = Field(default_factory=list)
    department: str | None
    employment_type: str | None
    workplace_type: str | None
    salary_min: float | None
    salary_max: float | None
    salary_currency: str | None
    salary_interval: str | None
    company_logo_url: str | None
    posting_url: str | None
    apply_url: str | None
    description_html: str | None
    description_text: str | None
    active: bool
    duplicate_status: str
    duplicate_of_job_id: int | None
    is_duplicate: bool
    reposted_at: datetime | None
    is_reposted: bool
    ranking_score: float
    ranking_reasons: list[str]
    posted_at: datetime | None
    source_updated_at: datetime | None
    first_seen_at: datetime
    last_seen_at: datetime
    closed_at: datetime | None
    is_saved: bool = False
    saved_job_id: int | None = None
    is_discarded: bool = False
    discarded_job_id: int | None = None
    discarded_at: datetime | None = None
    has_application: bool = False
    application_id: int | None = None
    application_status: ApplicationStatusRead | None = None
    is_seen: bool = False
    seen_at: datetime | None = None
    job_family_slug: str
    classification_confidence: float
    classification_method: str
    classification_reason: str
    classification_overridden_at: datetime | None = None
    sponsorship_status: str = "unknown"
    remote_scope: str = "not_remote"
    match_type: Literal["strict", "relaxed"] = "strict"
    relaxed_filters: list[str] = Field(default_factory=list)


class FacetEntryRead(BaseModel):
    value: str
    label: str
    count: int


class JobFeedFacetsRead(BaseModel):
    ats: list[FacetEntryRead] = Field(default_factory=list)
    sources: list[FacetEntryRead] = Field(default_factory=list)
    countries: list[FacetEntryRead] = Field(default_factory=list)
    workplace_types: list[FacetEntryRead] = Field(default_factory=list)
    salary_known: list[FacetEntryRead] = Field(default_factory=list)
    job_families: list[FacetEntryRead] = Field(default_factory=list)
    employment_types: list[FacetEntryRead] = Field(default_factory=list)


class JobFeedRead(BaseModel):
    items: list[JobPostingRead]
    total: int
    limit: int
    offset: int
    has_more: bool
    generated_at: datetime
    facets: JobFeedFacetsRead
    strict_total: int = 0
    relaxed_total: int = 0
    relaxed_filters: list[str] = Field(default_factory=list)
    relaxation_notice: str | None = None


class JobSummaryRead(BaseModel):
    id: int
    source_slug: str
    title: str
    company_name: str
    location: str | None
    location_country_code: str | None
    location_country: str | None
    locations: list[JobLocationRead] = Field(default_factory=list)
    salary_min: float | None
    salary_max: float | None
    salary_currency: str | None
    salary_interval: str | None
    company_logo_url: str | None
    apply_url: str | None
    ranking_score: float
    active: bool
    duplicate_status: str
    duplicate_of_job_id: int | None
    reposted_at: datetime | None
    job_family_slug: str
    sponsorship_status: str = "unknown"
    remote_scope: str = "not_remote"


PREFERENCE_LIST_FIELDS = (
    "include_keywords",
    "exclude_keywords",
    "role_groups",
    "preferred_levels",
    "preferred_locations",
    "selected_job_families",
    "related_job_families",
    "desired_titles",
    "preferred_countries",
    "excluded_countries",
    "workplace_preferences",
    "employment_types",
    "excluded_companies",
)
SUPPORTED_LEVELS = {
    "internship",
    "co-op",
    "new-grad",
    "entry-level",
    "experienced",
    "intern",
    "entry",
    "junior",
    "mid",
    "senior",
    "staff",
    "principal",
    "lead",
    "manager",
    "director",
}


def _normalized_unique_strings(values: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = value.strip()
        if not clean:
            raise ValueError("preference values cannot be empty")
        key = clean.casefold()
        if key not in seen:
            normalized.append(clean)
            seen.add(key)
    return normalized


class UserPreferenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    include_keywords: list[str]
    exclude_keywords: list[str]
    role_groups: list[str]
    preferred_levels: list[str]
    preferred_locations: list[str]
    home_location: str
    radius_miles: int
    country: str
    remote_allowed: bool
    minimum_score_threshold: float
    selected_job_families: list[str]
    related_job_families: list[str]
    desired_titles: list[str]
    preferred_countries: list[str]
    excluded_countries: list[str]
    workplace_preferences: list[str]
    employment_types: list[str]
    sponsorship_required: bool | None
    minimum_salary: Decimal | None
    excluded_companies: list[str]
    updated_at: datetime


class UserPreferenceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_keywords: list[str] | None = None
    exclude_keywords: list[str] | None = None
    role_groups: list[str] | None = None
    preferred_levels: list[str] | None = None
    preferred_locations: list[str] | None = None
    home_location: str | None = None
    radius_miles: int | None = Field(default=None, ge=0, le=500)
    country: str | None = None
    remote_allowed: bool | None = None
    minimum_score_threshold: float | None = Field(default=None, ge=0, le=100)
    selected_job_families: list[str] | None = None
    related_job_families: list[str] | None = None
    desired_titles: list[str] | None = None
    preferred_countries: list[str] | None = None
    excluded_countries: list[str] | None = None
    workplace_preferences: list[str] | None = None
    employment_types: list[str] | None = None
    sponsorship_required: bool | None = None
    minimum_salary: Decimal | None = Field(default=None, ge=0)
    excluded_companies: list[str] | None = None

    @field_validator(*PREFERENCE_LIST_FIELDS)
    @classmethod
    def normalize_lists(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _normalized_unique_strings(value)

    @field_validator("role_groups")
    @classmethod
    def validate_role_groups(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        unsupported = sorted(set(value) - set(ROLE_GROUPS))
        if unsupported:
            raise ValueError(f"unsupported role groups: {', '.join(unsupported)}")
        return value

    @field_validator("preferred_levels")
    @classmethod
    def validate_levels(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        unsupported = sorted({level.casefold() for level in value} - SUPPORTED_LEVELS)
        if unsupported:
            raise ValueError(f"unsupported job levels: {', '.join(unsupported)}")
        return [level.casefold() for level in value]

    @field_validator("selected_job_families", "related_job_families")
    @classmethod
    def validate_job_families(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized = [item.casefold().replace("_", "-") for item in value]
        unsupported = sorted(set(normalized) - JOB_FAMILY_SLUGS)
        if unsupported:
            raise ValueError(f"unsupported job families: {', '.join(unsupported)}")
        return normalized

    @field_validator("workplace_preferences")
    @classmethod
    def validate_workplaces(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized = [item.casefold() for item in value]
        unsupported = sorted(set(normalized) - {"remote", "hybrid", "on-site", "onsite"})
        if unsupported:
            raise ValueError(f"unsupported workplace preferences: {', '.join(unsupported)}")
        return normalized

    @field_validator("home_location", "country")
    @classmethod
    def validate_required_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        if not clean:
            raise ValueError("value cannot be empty")
        return clean


class RescoreResponse(BaseModel):
    total_jobs_considered: int
    total_jobs_rescored: int
    total_visible_jobs: int
    total_hidden_or_low_ranked_jobs: int
    started_at: datetime
    finished_at: datetime
    duration_ms: int


class OnboardingRead(BaseModel):
    state: Literal["pending", "completed", "skipped"]
    completed_at: datetime | None
    skipped_at: datetime | None
    preferences_help_relevance: bool


class OnboardingUpdate(BaseModel):
    action: Literal["complete", "skip", "reset"]


class SavedJobCreate(BaseModel):
    notes: str | None = Field(default=None, max_length=20_000)


class SavedJobUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notes: str | None = Field(default=None, max_length=20_000)


class SavedJobRead(BaseModel):
    id: int
    saved_at: datetime
    updated_at: datetime
    notes: str | None
    job: JobSummaryRead
    application_status: ApplicationStatusRead | None = None


class SavedJobDeleteResponse(BaseModel):
    job_id: int
    removed: bool


class DiscardedJobRead(BaseModel):
    id: int
    discarded_at: datetime
    job: JobSummaryRead


class DiscardedJobDeleteResponse(BaseModel):
    job_id: int
    restored: bool


class ApplicationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str | None = None
    notes: str | None = Field(default=None, max_length=20_000)
    create_new: bool = False
    link_url: str | None = Field(default=None, max_length=1000)


class ApplicationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str | None = None
    notes: str | None = Field(default=None, max_length=20_000)
    status_note: str | None = Field(default=None, max_length=20_000)
    link_url: str | None = Field(default=None, max_length=1000)


ManualEventType = Literal[
    "note",
    "follow_up",
    "online_assessment",
    "interview",
    "recruiter_contact",
    "rejection",
    "offer",
]


class ApplicationEventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: ManualEventType
    notes: str | None = Field(default=None, max_length=20_000)
    occurred_at: datetime | None = None


class ApplicationEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    application_id: int
    event_type: str
    old_status: str | None
    new_status: str | None
    notes: str | None
    occurred_at: datetime
    created_at: datetime


class ApplicationRead(BaseModel):
    id: int
    notes: str | None
    link_url: str | None = None
    deleted_at: datetime | None = None
    purge_after: datetime | None = None
    created_at: datetime
    updated_at: datetime
    status: ApplicationStatusRead
    job: JobSummaryRead | None = None
    manual_job: "ManualJobRead | None" = None
    source: SourceSummaryRead | None
    events: list[ApplicationEventRead] = Field(default_factory=list)


class ApplicationDeleteResponse(BaseModel):
    application_id: int
    job_id: int | None
    removed: bool
    purge_after: datetime | None = None


class ManualJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_name: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=500)
    location: str | None = Field(default=None, max_length=500)
    workplace_type: str | None = Field(default=None, max_length=120)
    job_family_slug: str = "other"
    posting_url: str | None = Field(default=None, max_length=1000)
    apply_url: str | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=20_000)
    application_status: str = "applied"
    application_notes: str | None = Field(default=None, max_length=20_000)
    application_link: str | None = Field(default=None, max_length=1000)

    @field_validator("job_family_slug")
    @classmethod
    def valid_family(cls, value: str) -> str:
        normalized = value.casefold().replace("_", "-")
        if normalized not in JOB_FAMILY_SLUGS:
            raise ValueError("unsupported job family")
        return normalized


class ManualJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_name: str
    title: str
    location: str | None
    workplace_type: str | None
    job_family_slug: str
    posting_url: str | None
    apply_url: str | None
    notes: str | None
    approval_status: str
    created_at: datetime


class ApplicationRestoreResponse(BaseModel):
    application_id: int
    restored: bool


class ApplicationStatusCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    standard_category: Literal["applied", "interview", "offer", "rejected", "withdrawn", "archived"]


class PublicJobRead(BaseModel):
    id: int
    title: str
    company_name: str
    location: str | None
    workplace_type: str | None
    employment_type: str | None
    job_family_slug: str
    salary_min: float | None
    salary_max: float | None
    salary_currency: str | None
    salary_interval: str | None
    apply_url: str | None
    posted_at: datetime | None


class ClassificationOverrideUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_family_slug: str
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("job_family_slug")
    @classmethod
    def classification_family(cls, value: str) -> str:
        normalized = value.casefold().replace("_", "-")
        if normalized not in JOB_FAMILY_SLUGS:
            raise ValueError("unsupported job family")
        return normalized


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    job_posting_id: int | None
    scrape_run_id: int | None
    dedupe_key: str
    payload_json: dict
    read_at: datetime | None
    created_at: datetime


class NotificationReadAllResponse(BaseModel):
    marked_read: int


class IngestRunRequest(BaseModel):
    source_slugs: list[str] | None = None
    dry_run: bool = False


class SourceRunSummaryRead(BaseModel):
    source_slug: str
    status: str
    fetched_count: int
    upserted_count: int
    new_jobs: int
    updated_jobs: int
    unchanged_jobs: int
    closed_count: int
    duplicates_found: int
    skipped_count: int
    error_count: int
    error_message: str | None
    duration_ms: int


class IngestRunResponse(BaseModel):
    status: str
    dry_run: bool
    sources_requested: list[str]
    total_fetched: int
    total_upserted: int
    total_new_jobs: int
    total_updated_jobs: int
    total_unchanged_jobs: int
    total_closed: int
    total_duplicates: int
    total_errors: int
    duration_ms: int
    scrape_run_id: int | None
    source_runs: list[SourceRunSummaryRead]


class ScrapeRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    dry_run: bool
    triggered_by: str
    sources_requested: list[str]
    total_sources_checked: int
    total_jobs_seen: int
    total_new_jobs: int
    total_updated_jobs: int
    total_unchanged_jobs: int
    total_closed_jobs: int
    total_duplicates: int
    total_fetched: int
    total_upserted: int
    total_closed: int
    total_errors: int
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    error_message: str | None


class ScrapeSourceRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    scrape_run_id: int
    source_slug: str
    status: str
    jobs_seen: int
    new_jobs: int
    updated_jobs: int
    unchanged_jobs: int
    closed_jobs: int
    duplicates_found: int
    fetched_count: int
    upserted_count: int
    closed_count: int
    error_count: int
    error_message: str | None
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None


class SourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str
    ats: str
    company_name: str
    company_logo_url: str | None
    careers_url: str | None
    enabled: bool
    priority: int
    poll_interval_minutes: int | None
    close_after_missed_runs: int
    categories: list[str]
    notes: str
    health_status: str
    consecutive_failures: int
    last_checked_at: datetime | None
    last_successful_at: datetime | None
    last_error: str | None
    next_due_at: datetime | None


class SourceSyncRead(BaseModel):
    created: int
    updated: int
    disabled: int


class OperationsIngestionRead(BaseModel):
    run_in_progress: bool
    last_run: ScrapeRunRead | None
    last_successful_at: datetime | None
    next_due_at: datetime | None


class OperationsSourcesRead(BaseModel):
    total: int
    enabled: int
    due: int
    healthy: int
    unhealthy: int
    items: list[SourceRead]


class OperationsJobsRead(BaseModel):
    active: int
    inactive: int
    new_last_24_hours: int
    updated_last_24_hours: int


class OperationsRead(BaseModel):
    generated_at: datetime
    ingestion: OperationsIngestionRead
    sources: OperationsSourcesRead
    jobs: OperationsJobsRead
    recent_runs: list[ScrapeRunRead]


class IngestionHealthLastRunRead(BaseModel):
    id: int
    status: str
    started_at: datetime
    finished_at: datetime | None


class IngestionHealthRead(BaseModel):
    status: Literal["ok", "degraded", "stale"]
    run_in_progress: bool
    last_run: IngestionHealthLastRunRead | None
    last_successful_at: datetime | None
    due_sources: int
    unhealthy_sources: int
    stale_running_runs: int


class DuplicateJobSummary(BaseModel):
    id: int
    title: str
    company_name: str
    location: str | None
    source_slug: str
    apply_url: str | None
    ranking_score: float
    first_seen_at: datetime
    last_seen_at: datetime
    active: bool
    duplicate_status: str


class DuplicateReviewRead(BaseModel):
    id: int
    candidate_job_id: int
    existing_job_id: int
    reason: str
    status: str
    signals_json: dict
    resolution_notes: str | None
    resolved_at: datetime | None
    created_at: datetime
    candidate_job: DuplicateJobSummary
    existing_job: DuplicateJobSummary


class DuplicateReviewUpdate(BaseModel):
    status: Literal["open", "merged", "not_duplicate", "dismissed"]
    resolution_notes: str | None = None
