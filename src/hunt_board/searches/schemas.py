from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from hunt_board.api.schemas import JobFeedFacetsRead, JobPostingRead, JobSummaryRead
from hunt_board.jobs.query import SortBy, SortOrder


class SavedSearchFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    q: str | None = Field(default=None, max_length=500)
    active: bool | None = True
    company: str | None = None
    source_slug: str | None = None
    ats: str | None = None
    location: str | None = None
    country: str | None = None
    workplace_type: str | None = None
    salary_known: bool | None = None
    duplicate_status: str | None = None
    include_duplicates: bool = False
    min_score: float | None = Field(default=None, ge=0, le=100)
    saved: bool | None = None
    discarded: bool | None = False
    application_status: str | None = None
    application_state: Literal["none", "tracked", "any"] = "none"
    remote_only: bool = False
    posted_within_days: int | None = Field(default=None, ge=1, le=3650)

    @field_validator(
        "q",
        "company",
        "source_slug",
        "ats",
        "location",
        "country",
        "workplace_type",
        "duplicate_status",
        "application_status",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        clean = value.strip()
        return clean or None

    @field_validator("ats")
    @classmethod
    def lowercase_ats(cls, value: str | None) -> str | None:
        return value.lower() if value else None

    @field_validator("country")
    @classmethod
    def normalize_country(cls, value: str | None) -> str | None:
        return value.upper() if value and len(value) == 2 else value

    @field_validator("application_state", mode="before")
    @classmethod
    def lowercase_application_state(cls, value: object) -> object:
        return value.lower() if isinstance(value, str) else value


class SavedSearchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    filters: SavedSearchFilters = Field(default_factory=SavedSearchFilters)
    sort_by: SortBy = "ranking_score"
    sort_order: SortOrder = "desc"
    is_default: bool = False
    is_active: bool = True
    notify_on_new_matches: bool = False

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        clean = value.strip()
        if not clean:
            raise ValueError("name cannot be empty")
        return clean

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        clean = value.strip()
        return clean or None

    @field_validator("sort_order", mode="before")
    @classmethod
    def lowercase_sort_order(cls, value: object) -> object:
        return value.lower() if isinstance(value, str) else value


class SavedSearchUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    filters: SavedSearchFilters | None = None
    sort_by: SortBy | None = None
    sort_order: SortOrder | None = None
    is_default: bool | None = None
    is_active: bool | None = None
    notify_on_new_matches: bool | None = None
    reset_reviewed: bool = False

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> object:
        if value is None:
            raise ValueError("name cannot be null")
        if not isinstance(value, str):
            return value
        clean = value.strip()
        if not clean:
            raise ValueError("name cannot be empty")
        return clean

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        clean = value.strip()
        return clean or None

    @field_validator("sort_order", mode="before")
    @classmethod
    def lowercase_sort_order(cls, value: object) -> object:
        return value.lower() if isinstance(value, str) else value

    @model_validator(mode="after")
    def reject_null_updates(self) -> SavedSearchUpdate:
        nullable = {"description"}
        for field_name in self.model_fields_set - nullable:
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class SavedSearchRead(BaseModel):
    id: int
    name: str
    description: str | None
    filters: SavedSearchFilters
    sort_by: SortBy
    sort_order: SortOrder
    is_default: bool
    is_active: bool
    notify_on_new_matches: bool
    last_viewed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    match_count: int | None = None
    new_since_review_count: int | None = None
    preview_jobs: list[JobSummaryRead] | None = None


class SavedSearchDeleteResponse(BaseModel):
    saved_search_id: int
    removed: bool


class SavedSearchMatchMetadata(BaseModel):
    id: int
    name: str
    last_viewed_at: datetime | None


class SavedSearchMatchesRead(BaseModel):
    saved_search: SavedSearchMatchMetadata
    items: list[JobPostingRead]
    total: int
    new_since_review_count: int
    limit: int
    offset: int
    has_more: bool
    generated_at: datetime
    facets: JobFeedFacetsRead


class SavedSearchReviewedRead(BaseModel):
    saved_search_id: int
    last_viewed_at: datetime
    match_count: int
    new_since_review_count: int
