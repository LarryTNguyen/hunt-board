from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint, Uuid
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
    """Hunt Board profile mapped to one trusted Supabase Auth identity."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    auth_user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True, unique=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    normalized_email: Mapped[str | None] = mapped_column(String(320), nullable=True, unique=True)
    first_name: Mapped[str | None] = mapped_column(String(120))
    last_name: Mapped[str | None] = mapped_column(String(120))
    display_name: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="user", nullable=False)
    account_status: Mapped[str] = mapped_column(String(40), default="active", nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deletion_scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    onboarding_skipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    preferences_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    applications: Mapped[list[Application]] = relationship(back_populates="user")
    preference: Mapped[UserPreference | None] = relationship(back_populates="user", uselist=False)
    saved_searches: Mapped[list[SavedSearch]] = relationship(back_populates="user")
    manual_jobs: Mapped[list[ManualJob]] = relationship(back_populates="user")


class Invitation(TimestampMixin, Base):
    __tablename__ = "invitations"
    __table_args__ = (
        Index("ix_invitations_email_status", "normalized_email", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    normalized_email: Mapped[str] = mapped_column(String(320), nullable=False)
    inviter_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="pending", nullable=False)
    accepted_auth_user_id: Mapped[UUID | None] = mapped_column(Uuid)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
    minimum_score_threshold: Mapped[float] = mapped_column(Float, default=60, nullable=False)
    selected_job_families: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    related_job_families: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    desired_titles: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    preferred_countries: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    excluded_countries: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    workplace_preferences: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    employment_types: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    sponsorship_required: Mapped[bool | None] = mapped_column(Boolean)
    minimum_salary: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    excluded_companies: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    user: Mapped[User] = relationship(back_populates="preference")


class Source(TimestampMixin, Base):
    __tablename__ = "sources"
    __table_args__ = (Index("ix_sources_enabled_next_due", "enabled", "next_due_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    ats: Mapped[str] = mapped_column(String(40), nullable=False)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    company_logo_url: Mapped[str | None] = mapped_column(String(1000))
    careers_url: Mapped[str | None] = mapped_column(String(1000))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    poll_interval_minutes: Mapped[int | None] = mapped_column(Integer)
    close_after_missed_runs: Mapped[int] = mapped_column(Integer, default=12, nullable=False)
    categories: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    health_status: Mapped[str] = mapped_column(String(40), default="unknown", nullable=False)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_successful_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    next_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    job_postings: Mapped[list[JobPosting]] = relationship(back_populates="source")


class JobFamily(TimestampMixin, Base):
    """Fixed private-beta taxonomy; application code exposes no mutation API."""

    __tablename__ = "job_families"

    slug: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)


class JobPosting(TimestampMixin, Base):
    __tablename__ = "job_postings"
    __table_args__ = (
        UniqueConstraint("source_id", "external_job_id", name="uq_job_postings_source_external_id"),
        Index("ix_job_postings_active", "active"),
        Index("ix_job_postings_canonical_apply_url", "canonical_apply_url"),
        Index("ix_job_postings_company_title_location", "company_name", "normalized_title", "normalized_location"),
        Index("ix_job_postings_posted_at", "posted_at"),
        Index("ix_job_postings_company_name", "company_name"),
        Index("ix_job_postings_title", "title"),
        Index("ix_job_postings_location", "location"),
        Index("ix_job_postings_location_country_code", "location_country_code"),
        Index("ix_job_postings_feed_default", "active", "duplicate_status", "ranking_score", "id"),
        Index("ix_job_postings_source_id", "source_id"),
        Index("ix_job_postings_family_active", "job_family_slug", "active"),
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
    location_country_code: Mapped[str | None] = mapped_column(String(2))
    location_country: Mapped[str | None] = mapped_column(String(120))
    locations_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    department: Mapped[str | None] = mapped_column(String(255))
    employment_type: Mapped[str | None] = mapped_column(String(120))
    workplace_type: Mapped[str | None] = mapped_column(String(120))
    salary_min: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    salary_max: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    salary_currency: Mapped[str | None] = mapped_column(String(3))
    salary_interval: Mapped[str | None] = mapped_column(String(40))
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
    job_family_slug: Mapped[str] = mapped_column(
        ForeignKey("job_families.slug"), default="other", nullable=False
    )
    classification_confidence: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    classification_method: Mapped[str] = mapped_column(String(40), default="fallback", nullable=False)
    classification_reason: Mapped[str] = mapped_column(String(500), default="Insufficient evidence", nullable=False)
    classification_overridden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    classification_overridden_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    classification_override_reason: Mapped[str | None] = mapped_column(String(500))
    sponsorship_status: Mapped[str] = mapped_column(String(40), default="unknown", nullable=False)
    remote_scope: Mapped[str] = mapped_column(String(40), default="not_remote", nullable=False)

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


class UserJobState(TimestampMixin, Base):
    """Canonical combined saved/dismissed state for one user and catalog job."""

    __tablename__ = "user_job_states"
    __table_args__ = (
        UniqueConstraint("user_id", "job_posting_id", name="uq_user_job_states_user_job"),
        Index("ix_user_job_states_user_saved", "user_id", "saved_at"),
        Index("ix_user_job_states_user_dismissed", "user_id", "dismissed_at"),
        Index("ix_user_job_states_user_seen", "user_id", "seen_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    job_posting_id: Mapped[int] = mapped_column(ForeignKey("job_postings.id"), nullable=False)
    saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)


class SavedSearch(TimestampMixin, Base):
    __tablename__ = "saved_searches"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_saved_searches_user_name"),
        Index("ix_saved_searches_user_active", "user_id", "is_active"),
        Index("ix_saved_searches_user_last_viewed", "user_id", "last_viewed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    filters_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    sort_by: Mapped[str] = mapped_column(String(40), default="ranking_score", nullable=False)
    sort_order: Mapped[str] = mapped_column(String(4), default="desc", nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notify_on_new_matches: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="saved_searches")


class DiscardedJob(TimestampMixin, Base):
    __tablename__ = "discarded_jobs"
    __table_args__ = (
        UniqueConstraint("user_id", "job_posting_id", name="uq_discarded_jobs_user_job"),
        Index("ix_discarded_jobs_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    job_posting_id: Mapped[int] = mapped_column(ForeignKey("job_postings.id"), nullable=False)


class ApplicationStatus(TimestampMixin, Base):
    __tablename__ = "application_statuses"
    __table_args__ = (
        UniqueConstraint("user_id", "slug", name="uq_application_statuses_user_slug"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    is_terminal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    standard_category: Mapped[str] = mapped_column(String(40), default="applied", nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ManualJob(TimestampMixin, Base):
    __tablename__ = "manual_jobs"
    __table_args__ = (Index("ix_manual_jobs_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    location: Mapped[str | None] = mapped_column(String(500))
    workplace_type: Mapped[str | None] = mapped_column(String(120))
    job_family_slug: Mapped[str] = mapped_column(ForeignKey("job_families.slug"), default="other", nullable=False)
    posting_url: Mapped[str | None] = mapped_column(String(1000))
    apply_url: Mapped[str | None] = mapped_column(String(1000))
    notes: Mapped[str | None] = mapped_column(Text)
    approval_status: Mapped[str] = mapped_column(String(40), default="private", nullable=False)

    user: Mapped[User] = relationship(back_populates="manual_jobs")
    applications: Mapped[list[Application]] = relationship(back_populates="manual_job")


class Application(TimestampMixin, Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    job_posting_id: Mapped[int | None] = mapped_column(ForeignKey("job_postings.id"))
    manual_job_id: Mapped[int | None] = mapped_column(ForeignKey("manual_jobs.id"))
    status_id: Mapped[int | None] = mapped_column(ForeignKey("application_statuses.id"))
    # status_id is canonical. This slug is retained as a compatibility snapshot
    # for clients created against the Milestone 1 schema.
    status: Mapped[str] = mapped_column(String(80), default="applied", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    link_url: Mapped[str | None] = mapped_column(String(1000))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purge_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="applications")
    job_posting: Mapped[JobPosting | None] = relationship(back_populates="applications")
    manual_job: Mapped[ManualJob | None] = relationship(back_populates="applications")


class ApplicationEvent(TimestampMixin, Base):
    __tablename__ = "application_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), nullable=False)
    status_id: Mapped[int | None] = mapped_column(ForeignKey("application_statuses.id"))
    event_type: Mapped[str] = mapped_column(String(80), default="status_changed", nullable=False)
    old_status: Mapped[str | None] = mapped_column(String(120))
    new_status: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Notification(TimestampMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("user_id", "dedupe_key", name="uq_notifications_user_dedupe_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    job_posting_id: Mapped[int | None] = mapped_column(ForeignKey("job_postings.id"))
    scrape_run_id: Mapped[int | None] = mapped_column(ForeignKey("scrape_runs.id"))
    kind: Mapped[str] = mapped_column(String(80), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(500), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditEvent(TimestampMixin, Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_event_created", "event_name", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_name: Mapped[str] = mapped_column(String(120), nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    target_type: Mapped[str | None] = mapped_column(String(80))
    target_id: Mapped[str | None] = mapped_column(String(255))
    request_id: Mapped[str | None] = mapped_column(String(64))
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


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
    __table_args__ = (Index("ix_scrape_runs_started_status", "started_at", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    triggered_by: Mapped[str] = mapped_column(String(80), default="api", nullable=False)
    sources_requested: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    total_sources_checked: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_jobs_seen: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_new_jobs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_updated_jobs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_unchanged_jobs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_closed_jobs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_duplicates: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_fetched: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_upserted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_closed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_errors: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)

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
    unchanged_jobs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
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
