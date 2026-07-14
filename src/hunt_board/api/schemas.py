from __future__ import annotations

from datetime import datetime

from typing import Literal

from pydantic import BaseModel, ConfigDict


class JobPostingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_slug: str
    company_name: str
    external_job_id: str | None
    title: str
    location: str | None
    department: str | None
    employment_type: str | None
    workplace_type: str | None
    posting_url: str | None
    apply_url: str | None
    description_text: str | None
    active: bool
    duplicate_status: str
    ranking_score: float
    ranking_reasons: list[str]
    posted_at: datetime | None
    source_updated_at: datetime | None
    first_seen_at: datetime
    last_seen_at: datetime


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
    closed_count: int
    duplicates_found: int
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
    total_closed_jobs: int
    total_duplicates: int
    total_fetched: int
    total_upserted: int
    total_closed: int
    total_errors: int
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None


class ScrapeSourceRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    scrape_run_id: int
    source_slug: str
    status: str
    jobs_seen: int
    new_jobs: int
    updated_jobs: int
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
    careers_url: str | None
    enabled: bool
    priority: int
    categories: list[str]
    notes: str
    health_status: str
    consecutive_failures: int
    last_successful_at: datetime | None
    next_due_at: datetime | None


class SourceSyncRead(BaseModel):
    created: int
    updated: int
    disabled: int


class DuplicateReviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    candidate_job_id: int
    existing_job_id: int
    reason: str
    status: str
    signals_json: dict
    resolution_notes: str | None
    resolved_at: datetime | None
    created_at: datetime


class DuplicateReviewUpdate(BaseModel):
    status: Literal["open", "merged", "not_duplicate", "dismissed"]
    resolution_notes: str | None = None
