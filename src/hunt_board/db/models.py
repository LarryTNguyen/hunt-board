from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hunt_board.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    preferences_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    applications: Mapped[list[Application]] = relationship(back_populates="user")
    preference: Mapped[UserPreference | None] = relationship(back_populates="user", uselist=False)


class UserPreference(TimestampMixin, Base):
    __tablename__ = "user_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, unique=True)
    include_keywords: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    exclude_keywords: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    role_groups: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    preferred_levels: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    preferred_locations: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    home_location: Mapped[str] = mapped_column(String(255), default="San Jose", nullable=False)
    radius_miles: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    country: Mapped[str] = mapped_column(String(120), default="USA", nullable=False)
    remote_allowed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user: Mapped[User] = relationship(back_populates="preference")


class Source(TimestampMixin, Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    ats: Mapped[str] = mapped_column(String(40), nullable=False)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    careers_url: Mapped[str | None] = mapped_column(String(1000))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    categories: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    health_status: Mapped[str] = mapped_column(String(40), default="unknown", nullable=False)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_successful_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    job_postings: Mapped[list[JobPosting]] = relationship(back_populates="source")


class JobPosting(TimestampMixin, Base):
    __tablename__ = "job_postings"
    __table_args__ = (
        UniqueConstraint("source_id", "external_job_id", name="uq_job_postings_source_external_id"),
        Index("ix_job_postings_active", "active"),
        Index("ix_job_postings_canonical_apply_url", "canonical_apply_url"),
        Index("ix_job_postings_company_title_location", "company_name", "normalized_title", "normalized_location"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    source_slug: Mapped[str] = mapped_column(String(120), nullable=False)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    external_job_id: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_title: Mapped[str] = mapped_column(String(500), nullable=False)
    location: Mapped[str | None] = mapped_column(String(500))
    normalized_location: Mapped[str | None] = mapped_column(String(500))
    department: Mapped[str | None] = mapped_column(String(255))
    employment_type: Mapped[str | None] = mapped_column(String(120))
    workplace_type: Mapped[str | None] = mapped_column(String(120))
    posting_url: Mapped[str | None] = mapped_column(String(1000))
    apply_url: Mapped[str | None] = mapped_column(String(1000))
    canonical_apply_url: Mapped[str | None] = mapped_column(String(1000))
    description_html: Mapped[str | None] = mapped_column(Text)
    description_text: Mapped[str | None] = mapped_column(Text)
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    raw_json_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    description_hash: Mapped[str | None] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    duplicate_status: Mapped[str] = mapped_column(String(40), default="unique", nullable=False)
    duplicate_of_job_id: Mapped[int | None] = mapped_column(ForeignKey("job_postings.id"))
    ranking_score: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    ranking_reasons: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reposted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consecutive_missed_runs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    source: Mapped[Source] = relationship(back_populates="job_postings")
    applications: Mapped[list[Application]] = relationship(back_populates="job_posting")
    versions: Mapped[list[JobVersion]] = relationship(back_populates="job_posting")


class JobVersion(TimestampMixin, Base):
    __tablename__ = "job_versions"
    __table_args__ = (UniqueConstraint("job_posting_id", "description_hash", name="uq_job_versions_job_hash"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_posting_id: Mapped[int] = mapped_column(ForeignKey("job_postings.id"), nullable=False)
    description_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    description_html: Mapped[str | None] = mapped_column(Text)
    description_text: Mapped[str | None] = mapped_column(Text)
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    raw_json_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    job_posting: Mapped[JobPosting] = relationship(back_populates="versions")


class JobMatch(TimestampMixin, Base):
    __tablename__ = "job_matches"
    __table_args__ = (UniqueConstraint("user_id", "job_posting_id", name="uq_job_matches_user_job"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    job_posting_id: Mapped[int] = mapped_column(ForeignKey("job_postings.id"), nullable=False)
    score: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    matched: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    reasons: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)


class SavedJob(TimestampMixin, Base):
    __tablename__ = "saved_jobs"
    __table_args__ = (UniqueConstraint("user_id", "job_posting_id", name="uq_saved_jobs_user_job"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    job_posting_id: Mapped[int] = mapped_column(ForeignKey("job_postings.id"), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)


class ApplicationStatus(TimestampMixin, Base):
    __tablename__ = "application_statuses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    is_terminal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Application(TimestampMixin, Base):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("user_id", "job_posting_id", name="uq_applications_user_job"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    job_posting_id: Mapped[int] = mapped_column(ForeignKey("job_postings.id"), nullable=False)
    status_id: Mapped[int | None] = mapped_column(ForeignKey("application_statuses.id"))
    status: Mapped[str] = mapped_column(String(80), default="saved", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    user: Mapped[User] = relationship(back_populates="applications")
    job_posting: Mapped[JobPosting] = relationship(back_populates="applications")


class ApplicationEvent(TimestampMixin, Base):
    __tablename__ = "application_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), nullable=False)
    status_id: Mapped[int | None] = mapped_column(ForeignKey("application_statuses.id"))
    event_type: Mapped[str] = mapped_column(String(80), default="status_changed", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Notification(TimestampMixin, Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(80), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DuplicateReview(TimestampMixin, Base):
    __tablename__ = "duplicate_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_job_id: Mapped[int] = mapped_column(ForeignKey("job_postings.id"), nullable=False)
    existing_job_id: Mapped[int] = mapped_column(ForeignKey("job_postings.id"), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="open", nullable=False)
    signals_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    resolution_notes: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ScrapeRun(TimestampMixin, Base):
    __tablename__ = "scrape_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    triggered_by: Mapped[str] = mapped_column(String(80), default="api", nullable=False)
    sources_requested: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    total_sources_checked: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_jobs_seen: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_new_jobs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_updated_jobs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_closed_jobs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_duplicates: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_fetched: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_upserted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_closed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_errors: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)

    source_runs: Mapped[list[ScrapeSourceRun]] = relationship(back_populates="scrape_run")


class ScrapeSourceRun(TimestampMixin, Base):
    __tablename__ = "scrape_source_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scrape_run_id: Mapped[int] = mapped_column(ForeignKey("scrape_runs.id"), nullable=False)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"))
    source_slug: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    jobs_seen: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    new_jobs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_jobs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    closed_jobs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicates_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fetched_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    upserted_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    closed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)

    scrape_run: Mapped[ScrapeRun] = relationship(back_populates="source_runs")


# The original implementation used `Source`; expose the milestone terminology
# without a table rename or a breaking import change.
JobSource = Source
