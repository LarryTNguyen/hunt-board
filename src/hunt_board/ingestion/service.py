from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from time import perf_counter

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from hunt_board.db.models import (
    DuplicateReview,
    JobMatch,
    JobPosting,
    JobVersion,
    ScrapeRun,
    ScrapeSourceRun,
    Source,
    User,
    UserPreference,
)
from hunt_board.ingestion.adapters import AshbyAdapter, ATSAdapter, GreenhouseAdapter, LeverAdapter, NormalizedJob
from hunt_board.ingestion.sources import SourceConfig, load_sources, select_sources
from hunt_board.jobs.dedupe import DedupeDecision, canonicalize_url, decide_dedupe, normalize_text
from hunt_board.matching.ranking import RankingResult, UserPreferences, rank_job


ADAPTERS = {
    "greenhouse": GreenhouseAdapter,
    "lever": LeverAdapter,
    "ashby": AshbyAdapter,
}
CLOSE_AFTER_MISSED_RUNS = 12
RAW_JSON_RETENTION_DAYS = 60


@dataclass
class SourceIngestionSummary:
    source_slug: str
    status: str
    fetched_count: int = 0
    upserted_count: int = 0
    new_jobs: int = 0
    updated_jobs: int = 0
    closed_count: int = 0
    duplicates_found: int = 0
    error_count: int = 0
    error_message: str | None = None
    duration_ms: int = 0


@dataclass
class IngestionSummary:
    status: str
    dry_run: bool
    sources_requested: list[str]
    total_fetched: int = 0
    total_upserted: int = 0
    total_new_jobs: int = 0
    total_updated_jobs: int = 0
    total_closed: int = 0
    total_duplicates: int = 0
    total_errors: int = 0
    duration_ms: int = 0
    scrape_run_id: int | None = None
    source_runs: list[SourceIngestionSummary] = field(default_factory=list)


class IngestionService:
    def __init__(
        self,
        sources_path: str,
        timeout_seconds: float = 20,
        adapter_overrides: dict[str, ATSAdapter] | None = None,
    ) -> None:
        self.sources_path = sources_path
        self.timeout_seconds = timeout_seconds
        self.adapter_overrides = adapter_overrides or {}

    async def run(
        self,
        db: Session,
        requested_slugs: list[str] | None = None,
        dry_run: bool = False,
        triggered_by: str = "api",
    ) -> IngestionSummary:
        started = perf_counter()
        source_configs = select_sources(load_sources(self.sources_path), requested_slugs)
        if not requested_slugs:
            source_configs = [source for source in source_configs if self._is_due(db, source)]
        summary = IngestionSummary(
            status="running",
            dry_run=dry_run,
            sources_requested=[source.slug for source in source_configs],
        )
        scrape_run: ScrapeRun | None = None
        if not dry_run:
            scrape_run = ScrapeRun(
                status="running",
                dry_run=False,
                triggered_by=triggered_by,
                sources_requested=summary.sources_requested,
            )
            db.add(scrape_run)
            db.flush()
            summary.scrape_run_id = scrape_run.id

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            for source_config in source_configs:
                source_summary = await self._ingest_source(db, source_config, client, scrape_run, dry_run)
                summary.source_runs.append(source_summary)
                summary.total_fetched += source_summary.fetched_count
                summary.total_upserted += source_summary.upserted_count
                summary.total_new_jobs += source_summary.new_jobs
                summary.total_updated_jobs += source_summary.updated_jobs
                summary.total_closed += source_summary.closed_count
                summary.total_duplicates += source_summary.duplicates_found
                summary.total_errors += source_summary.error_count

        if summary.total_errors == len(source_configs) and source_configs:
            summary.status = "failed"
        elif summary.total_errors:
            summary.status = "completed_with_errors"
        else:
            summary.status = "completed"
        summary.duration_ms = round((perf_counter() - started) * 1000)
        if scrape_run:
            scrape_run.status = summary.status
            scrape_run.total_sources_checked = len(summary.source_runs)
            scrape_run.total_jobs_seen = summary.total_fetched
            scrape_run.total_new_jobs = summary.total_new_jobs
            scrape_run.total_updated_jobs = summary.total_updated_jobs
            scrape_run.total_closed_jobs = summary.total_closed
            scrape_run.total_duplicates = summary.total_duplicates
            # Retain the original aggregate names for existing API clients.
            scrape_run.total_fetched = summary.total_fetched
            scrape_run.total_upserted = summary.total_upserted
            scrape_run.total_closed = summary.total_closed
            scrape_run.total_errors = summary.total_errors
            scrape_run.finished_at = datetime.now(timezone.utc)
            scrape_run.duration_ms = summary.duration_ms
            db.commit()
        return summary

    async def _ingest_source(
        self,
        db: Session,
        source_config: SourceConfig,
        client: httpx.AsyncClient,
        scrape_run: ScrapeRun | None,
        dry_run: bool,
    ) -> SourceIngestionSummary:
        started = perf_counter()
        source_row = self._ensure_source(db, source_config, dry_run)
        source_summary = SourceIngestionSummary(source_slug=source_config.slug, status="running")
        source_run: ScrapeSourceRun | None = None
        if scrape_run:
            source_run = ScrapeSourceRun(
                scrape_run_id=scrape_run.id,
                source_id=source_row.id if source_row else None,
                source_slug=source_config.slug,
                status="running",
            )
            db.add(source_run)
            db.flush()

        try:
            with db.begin_nested():
                adapter = self._adapter_for(source_config, client)
                jobs = await adapter.fetch_jobs(source_config)
                source_summary.fetched_count = len(jobs)
                seen_external_ids = {job.external_job_id for job in jobs}
                preferences = self._preferences(db)
                for job in jobs:
                    ranking = rank_job(job, preferences, source_config.priority)
                    decision = decide_dedupe(db, source_row, job)
                    if decision.reason == "same canonical apply_url":
                        source_summary.duplicates_found += 1
                    if dry_run:
                        if decision.action == "upsert":
                            source_summary.updated_jobs += 1
                        else:
                            source_summary.new_jobs += 1
                        if decision.action == "possible_duplicate":
                            source_summary.duplicates_found += 1
                    elif source_row:
                        outcome, duplicate_found = self._upsert_job(db, source_row, job, ranking, decision)
                        if outcome == "new":
                            source_summary.new_jobs += 1
                        else:
                            source_summary.updated_jobs += 1
                        source_summary.duplicates_found += int(duplicate_found)
                    source_summary.upserted_count += 1
                if not dry_run and source_row:
                    source_summary.closed_count = self._mark_closed(db, source_row, seen_external_ids)
            source_summary.status = "completed"
            if source_row and not dry_run:
                source_row.health_status = "healthy"
                source_row.consecutive_failures = 0
                source_row.last_successful_at = datetime.now(timezone.utc)
                source_row.next_due_at = self._next_due(source_config.priority)
        except Exception as exc:  # adapters isolate one source failure from the rest of the run
            source_summary.status = "failed"
            source_summary.upserted_count = 0
            source_summary.new_jobs = 0
            source_summary.updated_jobs = 0
            source_summary.closed_count = 0
            source_summary.duplicates_found = 0
            source_summary.error_count = 1
            source_summary.error_message = str(exc)
            if source_row and not dry_run:
                source_row.health_status = "unhealthy"
                source_row.consecutive_failures += 1
                source_row.next_due_at = datetime.now(timezone.utc) + timedelta(hours=24)

        source_summary.duration_ms = round((perf_counter() - started) * 1000)
        if source_run:
            source_run.status = source_summary.status
            source_run.jobs_seen = source_summary.fetched_count
            source_run.new_jobs = source_summary.new_jobs
            source_run.updated_jobs = source_summary.updated_jobs
            source_run.closed_jobs = source_summary.closed_count
            source_run.duplicates_found = source_summary.duplicates_found
            source_run.fetched_count = source_summary.fetched_count
            source_run.upserted_count = source_summary.upserted_count
            source_run.closed_count = source_summary.closed_count
            source_run.error_count = source_summary.error_count
            source_run.error_message = source_summary.error_message
            source_run.finished_at = datetime.now(timezone.utc)
            source_run.duration_ms = source_summary.duration_ms
            db.flush()
        return source_summary

    def _adapter_for(self, source_config: SourceConfig, client: httpx.AsyncClient) -> ATSAdapter:
        override = self.adapter_overrides.get(source_config.slug)
        if override:
            return override
        return ADAPTERS[source_config.ats](client)

    def _ensure_source(self, db: Session, source_config: SourceConfig, dry_run: bool) -> Source | None:
        existing = db.scalar(select(Source).where(Source.slug == source_config.slug))
        if existing:
            if not dry_run:
                self._apply_source_config(existing, source_config)
            return existing
        if dry_run:
            return None
        source = Source(slug=source_config.slug, name=source_config.name, ats=source_config.ats, company_name=source_config.company_name)
        self._apply_source_config(source, source_config)
        db.add(source)
        db.flush()
        return source

    @staticmethod
    def _apply_source_config(source: Source, config: SourceConfig) -> None:
        source.name = config.name
        source.ats = config.ats
        source.company_name = config.company_name
        source.careers_url = config.careers_url
        source.enabled = config.enabled
        source.priority = config.priority
        source.categories = config.categories
        source.notes = config.notes
        source.config_json = config.config

    @staticmethod
    def _preferences(db: Session) -> UserPreferences:
        preference = db.scalar(select(UserPreference).order_by(UserPreference.id))
        if preference:
            return UserPreferences(
                include_keywords=preference.include_keywords,
                exclude_keywords=preference.exclude_keywords,
                role_groups=preference.role_groups,
                preferred_levels=preference.preferred_levels,
                preferred_locations=preference.preferred_locations,
                home_location=preference.home_location,
                radius_miles=preference.radius_miles,
                country=preference.country,
                remote_allowed=preference.remote_allowed,
            )
        user = db.scalar(select(User).order_by(User.id))
        return UserPreferences.model_validate(user.preferences_json or {}) if user else UserPreferences()

    def _upsert_job(
        self,
        db: Session,
        source: Source,
        job: NormalizedJob,
        ranking: RankingResult,
        decision: DedupeDecision,
    ) -> tuple[str, bool]:
        now = datetime.now(timezone.utc)
        target = decision.existing_job if decision.action == "upsert" else None
        outcome = "updated" if target else "new"
        if target is None:
            target = JobPosting(
                source_id=source.id,
                source_slug=source.slug,
                company_name=job.company_name,
                external_job_id=job.external_job_id,
                title=job.title,
                normalized_title=normalize_text(job.title) or "",
                location=self._display_location(job),
                normalized_location=normalize_text(self._display_location(job)),
                raw_json=job.raw_json,
            )
            db.add(target)
            db.flush()
        elif decision.reactivated:
            target.reposted_at = now

        # A canonical-URL match across sources represents one normalized posting;
        # preserve the source/external identity that owns that record.
        if target.source_id == source.id:
            target.external_job_id = job.external_job_id
            target.source_slug = source.slug
        target.company_name = job.company_name
        target.title = job.title
        target.normalized_title = normalize_text(job.title) or ""
        target.location = self._display_location(job)
        target.normalized_location = normalize_text(target.location)
        target.department = job.department
        target.employment_type = job.employment_type
        target.workplace_type = job.workplace_type
        target.posting_url = job.posting_url
        target.apply_url = job.apply_url
        target.canonical_apply_url = canonicalize_url(job.apply_url)
        target.active = True
        target.closed_at = None
        target.consecutive_missed_runs = 0
        target.last_seen_at = now
        target.posted_at = job.posted_at or target.posted_at or target.first_seen_at
        target.source_updated_at = job.updated_at
        target.ranking_score = ranking.score
        target.ranking_reasons = ranking.reasons
        target.raw_json = job.raw_json
        target.raw_json_expires_at = now + timedelta(days=RAW_JSON_RETENTION_DAYS)
        self._record_version(db, target, job)

        duplicate_found = decision.action == "possible_duplicate" and decision.existing_job is not None
        if duplicate_found:
            target.duplicate_status = "possible_duplicate"
            target.duplicate_of_job_id = decision.existing_job.id
            db.flush()
            open_review = db.scalar(
                select(DuplicateReview).where(
                    DuplicateReview.candidate_job_id == target.id,
                    DuplicateReview.existing_job_id == decision.existing_job.id,
                    DuplicateReview.status == "open",
                )
            )
            if not open_review:
                db.add(
                    DuplicateReview(
                        candidate_job_id=target.id,
                        existing_job_id=decision.existing_job.id,
                        reason=decision.reason or "possible duplicate",
                        signals_json={
                            "company_name": job.company_name,
                            "normalized_title": target.normalized_title,
                            "normalized_location": target.normalized_location,
                        },
                    )
                )
        elif decision.reason != "same canonical apply_url":
            target.duplicate_status = "unique"
            target.duplicate_of_job_id = None
        self._record_match(db, target, ranking)
        db.flush()
        return outcome, duplicate_found

    @staticmethod
    def _record_version(db: Session, target: JobPosting, job: NormalizedJob) -> None:
        description = job.description_text or job.description_html or ""
        description_hash = hashlib.sha256(description.encode("utf-8")).hexdigest()
        if target.description_hash == description_hash:
            return
        target.description_hash = description_hash
        target.description_html = job.description_html
        target.description_text = job.description_text
        db.flush()
        existing_version = db.scalar(
            select(JobVersion).where(
                JobVersion.job_posting_id == target.id,
                JobVersion.description_hash == description_hash,
            )
        )
        if not existing_version:
            db.add(
                JobVersion(
                    job_posting_id=target.id,
                    description_hash=description_hash,
                    description_html=job.description_html,
                    description_text=job.description_text,
                    raw_json=job.raw_json,
                    raw_json_expires_at=datetime.now(timezone.utc) + timedelta(days=RAW_JSON_RETENTION_DAYS),
                )
            )

    @staticmethod
    def _record_match(db: Session, target: JobPosting, ranking: RankingResult) -> None:
        user = db.scalar(select(User).order_by(User.id))
        if not user:
            return
        match = db.scalar(
            select(JobMatch).where(JobMatch.user_id == user.id, JobMatch.job_posting_id == target.id)
        )
        if not match:
            match = JobMatch(user_id=user.id, job_posting_id=target.id)
            db.add(match)
        match.score = ranking.score
        match.matched = ranking.matched
        match.reasons = ranking.reasons

    @staticmethod
    def _mark_closed(db: Session, source: Source, seen_external_ids: set[str]) -> int:
        active_jobs = db.scalars(
            select(JobPosting).where(JobPosting.source_id == source.id, JobPosting.active.is_(True))
        ).all()
        now = datetime.now(timezone.utc)
        closed_count = 0
        for job in active_jobs:
            if job.external_job_id in seen_external_ids:
                job.consecutive_missed_runs = 0
                continue
            job.consecutive_missed_runs += 1
            if job.consecutive_missed_runs >= CLOSE_AFTER_MISSED_RUNS:
                job.active = False
                job.closed_at = now
                closed_count += 1
        db.flush()
        return closed_count

    @staticmethod
    def _display_location(job: NormalizedJob) -> str | None:
        location = job.location
        combined = normalize_text(" ".join(filter(None, [location, job.workplace_type]))) or ""
        known_country = any(token in combined for token in ("united states", " usa ", " us ", "canada", "uk", "europe"))
        if "remote" in combined and not known_country:
            return "Remote - country unknown"
        return location

    @staticmethod
    def _next_due(priority: int) -> datetime:
        hours = 6 if priority >= 5 else 12 if priority >= 3 else 24
        return datetime.now(timezone.utc) + timedelta(hours=hours)

    @staticmethod
    def _is_due(db: Session, config: SourceConfig) -> bool:
        source = db.scalar(select(Source).where(Source.slug == config.slug))
        if not source or not source.next_due_at:
            return True
        next_due = source.next_due_at
        if next_due.tzinfo is None:
            next_due = next_due.replace(tzinfo=timezone.utc)
        return next_due <= datetime.now(timezone.utc)
