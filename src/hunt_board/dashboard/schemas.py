from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field

from hunt_board.api.schemas import ApplicationStatusRead, JobPostingRead, JobSummaryRead
from hunt_board.searches.schemas import SavedSearchRead


class DailyTotalsRead(BaseModel):
    active_jobs: int
    jobs_first_seen_last_24_hours: int
    jobs_first_seen_last_7_days: int
    saved_jobs: int
    discarded_jobs: int
    active_applications: int
    terminal_applications: int
    unread_notifications: int
    open_duplicate_reviews: int
    active_saved_searches: int
    saved_search_new_matches: int


class ApplicationPipelineItemRead(BaseModel):
    slug: str
    name: str
    sort_order: int
    count: int


class FollowUpCandidateRead(BaseModel):
    id: int
    notes: str | None
    created_at: datetime
    updated_at: datetime
    status: ApplicationStatusRead
    job: JobSummaryRead


class DailyDashboardRead(BaseModel):
    generated_at: datetime
    totals: DailyTotalsRead
    saved_searches: list[SavedSearchRead] = Field(default_factory=list)
    top_new_matches: list[JobPostingRead] = Field(default_factory=list)
    application_pipeline: list[ApplicationPipelineItemRead] = Field(default_factory=list)
    follow_up_candidates: list[FollowUpCandidateRead] = Field(default_factory=list)
