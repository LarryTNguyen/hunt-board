from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from time import perf_counter

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from hunt_board.db.models import (
    Application,
    DuplicateReview,
    JobMatch,
    JobPosting,
    JobVersion,
    Notification,
    SavedJob,
    ScrapeRun,
    ScrapeSourceRun,
    Source,
    User,
    UserPreference,
)
from hunt_board.ingestion.adapters import ATSAdapter, NormalizedJob, create_adapter
from hunt_board.ingestion.lock import (
    IngestionAlreadyRunningError,
    IngestionRunLock,
    ingestion_lock_for,
)
from hunt_board.ingestion.sanitizer import sanitized_description
from hunt_board.ingestion.sources import SourceConfig, load_sources, select_sources
from hunt_board.jobs.dedupe import DedupeDecision, canonicalize_url, decide_dedupe, normalize_text
from hunt_board.matching.ranking import RankingResult, UserPreferences, rank_job


RAW_JSON_RETENTION_DAYS = 60
logger = logging.getLogger(__name__)


@dataclass
class SourceIngestionSummary:
    source_slug: str
    status: str
    fetched_count: int = 0
    upserted_count: int = 0
    new_jobs: int = 0
    updated_jobs: int = 0
    unchanged_jobs: int = 0
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
    total_unchanged_jobs: int = 0
    total_closed: int = 0
    total_duplicates: int = 0
    total_errors: int = 0
    duration_ms: int = 0
    scrape_run_id: int | None = None
    source_runs: list[SourceIngestionSummary] = field(default_factory=list)


@dataclass
class _SourceFetchResult:
    source: SourceConfig
    started_at: datetime
    finished_at: datetime
    jobs: list[NormalizedJob] = field(default_factory=list)
    error_message: str | None = None


class IngestionService:
    def __init__(
        self,
        sources_path: str,
        timeout_seconds: float = 10,
        source_concurrency: int = 5,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.5,
        adapter_overrides: dict[str, ATSAdapter] | None = None,
        run_lock: IngestionRunLock | None = None,
        stale_run_minutes: int = 120,
    ) -> None:
        self.sources_path = sources_path
        self.timeout_seconds = timeout_seconds
        self.source_concurrency = max(1, source_concurrency)
        self.max_retries = max(0, max_retries)
        self.retry_backoff_seconds = max(0, retry_backoff_seconds)
        self.adapter_overrides = adapter_overrides or {}
        self.run_lock = run_lock
        self.stale_run_minutes = max(5, stale_run_minutes)

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
        if not source_configs:
            summary.status = "completed"
            summary.duration_ms = round((perf_counter() - started) * 1000)
            logger.info("Ingestion finished without a run because no sources are due")
            return summary
        scrape_run: ScrapeRun | None = None
        run_lock: IngestionRunLock | None = None
        if dry_run:
            return await self._execute_run(db, source_configs, summary, None, started)

        run_lock = self.run_lock or ingestion_lock_for(db)
        if not run_lock.acquire(db):
            logger.warning("Ingestion run rejected because another real run holds the lock")
            raise IngestionAlreadyRunningError("Another ingestion run is already in progress")
        try:
            self._recover_stale_runs(db)
            scrape_run = ScrapeRun(
                status="running",
                dry_run=False,
                triggered_by=triggered_by,
                sources_requested=summary.sources_requested,
            )
            db.add(scrape_run)
            db.commit()
            summary.scrape_run_id = scrape_run.id
            logger.info("Ingestion run %s started", scrape_run.id)
            try:
                return await self._execute_run(db, source_configs, summary, scrape_run, started)
            except BaseException as exc:
                self._finalize_unexpected_failure(db, scrape_run.id, exc, started)
                raise
        finally:
            run_lock.release()

    async def _execute_run(
        self,
        db: Session,
        source_configs: list[SourceConfig],
        summary: IngestionSummary,
        scrape_run: ScrapeRun | None,
        started: float,
    ) -> IngestionSummary:
        limits = httpx.Limits(max_connections=self.source_concurrency, max_keepalive_connections=self.source_concurrency)
        async with httpx.AsyncClient(timeout=self.timeout_seconds, limits=limits) as client:
            semaphore = asyncio.Semaphore(self.source_concurrency)
            fetch_results = await asyncio.gather(
                *(self._fetch_source(source, client, semaphore) for source in source_configs)
            )
            for fetch_result in fetch_results:
                source_summary = self._process_source(db, fetch_result, scrape_run, summary.dry_run)
                summary.source_runs.append(source_summary)
                summary.total_fetched += source_summary.fetched_count
                summary.total_upserted += source_summary.upserted_count
                summary.total_new_jobs += source_summary.new_jobs
                summary.total_updated_jobs += source_summary.updated_jobs
                summary.total_unchanged_jobs += source_summary.unchanged_jobs
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
            scrape_run.total_unchanged_jobs = summary.total_unchanged_jobs
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
            logger.info("Ingestion run %s finished with status %s", scrape_run.id, summary.status)
        return summary

    def _recover_stale_runs(self, db: Session) -> int:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=self.stale_run_minutes)
        stale_runs = list(
            db.scalars(
                select(ScrapeRun).where(
                    ScrapeRun.status == "running",
                    ScrapeRun.started_at < cutoff,
                )
            ).all()
        )
        for run in stale_runs:
            reason = f"Abandoned during startup recovery after exceeding {self.stale_run_minutes} minutes"
            run.status = "abandoned"
            run.error_message = reason
            run.finished_at = now
            run.duration_ms = self._duration_since(run.started_at, now)
            source_runs = db.scalars(
                select(ScrapeSourceRun).where(
                    ScrapeSourceRun.scrape_run_id == run.id,
                    ScrapeSourceRun.status == "running",
                )
            ).all()
            for source_run in source_runs:
                source_run.status = "abandoned"
                source_run.error_message = reason
                source_run.finished_at = now
                source_run.duration_ms = self._duration_since(source_run.started_at, now)
            logger.warning("Recovered stale ingestion run %s as abandoned", run.id)
        stale_source_runs = db.scalars(
            select(ScrapeSourceRun).where(
                ScrapeSourceRun.status == "running",
                ScrapeSourceRun.started_at < cutoff,
            )
        ).all()
        for source_run in stale_source_runs:
            reason = f"Abandoned during startup recovery after exceeding {self.stale_run_minutes} minutes"
            source_run.status = "abandoned"
            source_run.error_message = reason
            source_run.finished_at = now
            source_run.duration_ms = self._duration_since(source_run.started_at, now)
        return len(stale_runs)

    @staticmethod
    def _duration_since(started_at: datetime, finished_at: datetime) -> int:
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        return max(0, round((finished_at - started_at).total_seconds() * 1000))

    def _finalize_unexpected_failure(
        self,
        db: Session,
        scrape_run_id: int,
        exc: BaseException,
        started: float,
    ) -> None:
        db.rollback()
        run = db.get(ScrapeRun, scrape_run_id)
        if run is None:
            return
        finished_at = datetime.now(timezone.utc)
        message = f"{type(exc).__name__}: {exc}"[:4000]
        run.status = "failed"
        run.error_message = message
        run.finished_at = finished_at
        run.duration_ms = round((perf_counter() - started) * 1000)
        for source_run in db.scalars(
            select(ScrapeSourceRun).where(
                ScrapeSourceRun.scrape_run_id == scrape_run_id,
                ScrapeSourceRun.status == "running",
            )
        ).all():
            source_run.status = "failed"
            source_run.error_message = message
            source_run.finished_at = finished_at
            source_run.duration_ms = self._duration_since(source_run.started_at, finished_at)
        db.commit()
        logger.error(
            "Ingestion run %s failed unexpectedly",
            scrape_run_id,
            exc_info=(type(exc), exc, exc.__traceback__),
        )

    async def _fetch_source(
        self,
        source_config: SourceConfig,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
    ) -> _SourceFetchResult:
        started_at = datetime.now(timezone.utc)
        logger.info("Ingestion source %s started", source_config.slug)
        try:
            async with semaphore:
                adapter = self._adapter_for(source_config, client)
                jobs = await adapter.fetch_jobs(source_config)
                jobs = [self._sanitize_job(job) for job in jobs]
            return _SourceFetchResult(
                source=source_config,
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                jobs=jobs,
            )
        except Exception as exc:  # each fetch is isolated so other sources can finish
            return _SourceFetchResult(
                source=source_config,
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                error_message=str(exc),
            )

    def _process_source(
        self,
        db: Session,
        fetch_result: _SourceFetchResult,
        scrape_run: ScrapeRun | None,
        dry_run: bool,
    ) -> SourceIngestionSummary:
        source_config = fetch_result.source
        source_row = self._ensure_source(db, source_config, dry_run)
        source_summary = SourceIngestionSummary(
            source_slug=source_config.slug,
            status="running",
            fetched_count=len(fetch_result.jobs),
        )
        source_run: ScrapeSourceRun | None = None
        if scrape_run:
            source_run = ScrapeSourceRun(
                scrape_run_id=scrape_run.id,
                source_id=source_row.id if source_row else None,
                source_slug=source_config.slug,
                status="running",
                started_at=fetch_result.started_at,
            )
            db.add(source_run)
            db.flush()

        try:
            if fetch_result.error_message:
                raise RuntimeError(fetch_result.error_message)
            with db.begin_nested():
                seen_external_ids = {job.external_job_id for job in fetch_result.jobs}
                preferences = self._preferences(db)
                for job in fetch_result.jobs:
                    ranking = rank_job(job, preferences, source_config.priority)
                    decision = decide_dedupe(db, source_row, job)
                    if decision.reason == "same canonical apply_url":
                        source_summary.duplicates_found += 1
                    if dry_run:
                        if (
                            decision.action == "upsert"
                            and decision.existing_job is not None
                            and not decision.reactivated
                            and not self._job_changed(decision.existing_job, job, ranking)
                        ):
                            outcome = "unchanged"
                        elif decision.action == "upsert":
                            outcome = "updated"
                        else:
                            outcome = "new"
                        if outcome == "updated":
                            source_summary.updated_jobs += 1
                        elif outcome == "new":
                            source_summary.new_jobs += 1
                        else:
                            source_summary.unchanged_jobs += 1
                        if decision.action == "possible_duplicate":
                            source_summary.duplicates_found += 1
                    elif source_row:
                        outcome, duplicate_found = self._upsert_job(
                            db, source_row, job, ranking, decision, scrape_run
                        )
                        if outcome == "new":
                            source_summary.new_jobs += 1
                        elif outcome == "updated":
                            source_summary.updated_jobs += 1
                        else:
                            source_summary.unchanged_jobs += 1
                        source_summary.duplicates_found += int(duplicate_found)
                    if outcome != "unchanged":
                        source_summary.upserted_count += 1
                if not dry_run and source_row:
                    source_summary.closed_count = self._mark_closed(
                        db,
                        source_row,
                        seen_external_ids,
                        source_config.close_after_missed_runs,
                    )
            source_summary.status = "completed"
            if source_row and not dry_run:
                source_row.health_status = "healthy"
                source_row.consecutive_failures = 0
                source_row.last_successful_at = datetime.now(timezone.utc)
                source_row.last_error = None
                source_row.next_due_at = self._next_due(source_config.effective_poll_interval_minutes)
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
                source_row.last_error = source_summary.error_message
                source_row.next_due_at = datetime.now(timezone.utc) + timedelta(hours=24)
            logger.warning(
                "Ingestion source %s failed in run %s: %s",
                source_config.slug,
                scrape_run.id if scrape_run else "dry-run",
                source_summary.error_message,
            )

        finished_at = datetime.now(timezone.utc)
        if source_row and not dry_run:
            source_row.last_checked_at = finished_at
        source_summary.duration_ms = max(
            0,
            round((finished_at - fetch_result.started_at).total_seconds() * 1000),
        )
        if source_run:
            source_run.status = source_summary.status
            source_run.jobs_seen = source_summary.fetched_count
            source_run.new_jobs = source_summary.new_jobs
            source_run.updated_jobs = source_summary.updated_jobs
            source_run.unchanged_jobs = source_summary.unchanged_jobs
            source_run.closed_jobs = source_summary.closed_count
            source_run.duplicates_found = source_summary.duplicates_found
            source_run.fetched_count = source_summary.fetched_count
            source_run.upserted_count = source_summary.upserted_count
            source_run.closed_count = source_summary.closed_count
            source_run.error_count = source_summary.error_count
            source_run.error_message = source_summary.error_message
            source_run.finished_at = finished_at
            source_run.duration_ms = source_summary.duration_ms
            db.flush()
        logger.info(
            "Ingestion source %s finished with status %s",
            source_config.slug,
            source_summary.status,
        )
        return source_summary

    def _adapter_for(self, source_config: SourceConfig, client: httpx.AsyncClient) -> ATSAdapter:
        override = self.adapter_overrides.get(source_config.slug)
        if override:
            return override
        return create_adapter(
            source_config.ats,
            client,
            max_retries=self.max_retries,
            retry_backoff_seconds=self.retry_backoff_seconds,
        )

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
        source.company_logo_url = config.company_logo_url
        source.careers_url = config.careers_url
        source.enabled = config.enabled
        source.priority = config.priority
        source.poll_interval_minutes = config.effective_poll_interval_minutes
        source.close_after_missed_runs = config.close_after_missed_runs
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
                minimum_score_threshold=preference.minimum_score_threshold,
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
        scrape_run: ScrapeRun | None,
    ) -> tuple[str, bool]:
        now = datetime.now(timezone.utc)
        target = decision.existing_job if decision.action == "upsert" else None
        if (
            target is not None
            and not decision.reactivated
            and not self._job_changed(target, job, ranking)
        ):
            # The normalized posting is unchanged; only observation metadata must move.
            target.last_seen_at = now
            target.consecutive_missed_runs = 0
            target.raw_json = job.raw_json
            target.raw_json_expires_at = now + timedelta(days=RAW_JSON_RETENTION_DAYS)
            db.flush()
            return "unchanged", False
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
        target.location_country_code = job.location_country_code
        target.location_country = job.location_country
        target.department = job.department
        target.employment_type = job.employment_type
        target.workplace_type = job.workplace_type
        target.salary_min = job.salary_min
        target.salary_max = job.salary_max
        target.salary_currency = job.salary_currency
        target.salary_interval = job.salary_interval
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
        version = self._record_version(db, target, job)

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
        self._record_notifications(
            db,
            target,
            ranking,
            outcome=outcome,
            reactivated=decision.reactivated,
            changed_version=version if outcome == "updated" else None,
            scrape_run=scrape_run,
        )
        db.flush()
        return outcome, duplicate_found

    @classmethod
    def _job_changed(
        cls,
        target: JobPosting,
        job: NormalizedJob,
        ranking: RankingResult,
    ) -> bool:
        location = cls._display_location(job)
        expected_posted_at = job.posted_at or target.posted_at or target.first_seen_at
        relevant_values = (
            (target.company_name, job.company_name),
            (target.title, job.title),
            (target.normalized_title, normalize_text(job.title) or ""),
            (target.location, location),
            (target.normalized_location, normalize_text(location)),
            (target.location_country_code, job.location_country_code),
            (target.location_country, job.location_country),
            (target.department, job.department),
            (target.employment_type, job.employment_type),
            (target.workplace_type, job.workplace_type),
            (target.salary_min, job.salary_min),
            (target.salary_max, job.salary_max),
            (target.salary_currency, job.salary_currency),
            (target.salary_interval, job.salary_interval),
            (target.posting_url, job.posting_url),
            (target.apply_url, job.apply_url),
            (target.canonical_apply_url, canonicalize_url(job.apply_url)),
            (target.description_html, job.description_html),
            (target.description_text, job.description_text),
            (target.posted_at, expected_posted_at),
            (target.source_updated_at, job.updated_at),
            (target.ranking_score, ranking.score),
            (target.ranking_reasons, ranking.reasons),
        )
        return not target.active or any(current != incoming for current, incoming in relevant_values)

    @staticmethod
    def _record_version(db: Session, target: JobPosting, job: NormalizedJob) -> JobVersion | None:
        description = job.description_text or job.description_html or ""
        description_hash = hashlib.sha256(description.encode("utf-8")).hexdigest()
        if target.description_hash == description_hash:
            return None
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
            existing_version = JobVersion(
                job_posting_id=target.id,
                description_hash=description_hash,
                description_html=job.description_html,
                description_text=job.description_text,
                raw_json=job.raw_json,
                raw_json_expires_at=datetime.now(timezone.utc) + timedelta(days=RAW_JSON_RETENTION_DAYS),
            )
            db.add(existing_version)
            db.flush()
        return existing_version

    @classmethod
    def _record_notifications(
        cls,
        db: Session,
        job: JobPosting,
        ranking: RankingResult,
        *,
        outcome: str,
        reactivated: bool,
        changed_version: JobVersion | None,
        scrape_run: ScrapeRun | None,
    ) -> None:
        user = db.scalar(select(User).where(User.is_active.is_(True)).order_by(User.id))
        if user is None:
            return
        preference = db.scalar(select(UserPreference).where(UserPreference.user_id == user.id))
        threshold = preference.minimum_score_threshold if preference else UserPreferences().minimum_score_threshold
        qualifies = (
            job.active
            and job.duplicate_status != "duplicate"
            and ranking.matched
            and ranking.score >= threshold
        )
        if outcome == "new" and qualifies:
            cls._add_notification(
                db,
                user_id=user.id,
                job=job,
                scrape_run=scrape_run,
                kind="new_match",
                dedupe_key=f"new_match:{user.id}:{job.id}",
                message="New job match above your score threshold",
            )
        if reactivated and qualifies and job.reposted_at is not None:
            cls._add_notification(
                db,
                user_id=user.id,
                job=job,
                scrape_run=scrape_run,
                kind="reposted_job",
                dedupe_key=f"reposted_job:{user.id}:{job.id}:{job.reposted_at.isoformat()}",
                message="A matching job was reposted or reactivated",
            )
        if changed_version is not None:
            is_tracked = db.scalar(
                select(SavedJob.id).where(
                    SavedJob.user_id == user.id,
                    SavedJob.job_posting_id == job.id,
                )
            ) is not None or db.scalar(
                select(Application.id).where(
                    Application.user_id == user.id,
                    Application.job_posting_id == job.id,
                )
            ) is not None
            if is_tracked:
                cls._add_notification(
                    db,
                    user_id=user.id,
                    job=job,
                    scrape_run=scrape_run,
                    kind="job_updated",
                    dedupe_key=f"job_updated:{user.id}:{job.id}:{changed_version.id}",
                    message="A saved or applied job changed",
                )

    @staticmethod
    def _add_notification(
        db: Session,
        *,
        user_id: int,
        job: JobPosting,
        scrape_run: ScrapeRun | None,
        kind: str,
        dedupe_key: str,
        message: str,
    ) -> None:
        if db.scalar(select(Notification.id).where(Notification.dedupe_key == dedupe_key)) is not None:
            return
        db.add(
            Notification(
                user_id=user_id,
                job_posting_id=job.id,
                scrape_run_id=scrape_run.id if scrape_run else None,
                kind=kind,
                dedupe_key=dedupe_key,
                payload_json={
                    "job_id": job.id,
                    "title": job.title,
                    "company_name": job.company_name,
                    "ranking_score": job.ranking_score,
                    "message": message,
                },
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
    def _mark_closed(
        db: Session,
        source: Source,
        seen_external_ids: set[str],
        close_after_missed_runs: int,
    ) -> int:
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
            if job.consecutive_missed_runs >= close_after_missed_runs:
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
    def _next_due(poll_interval_minutes: int) -> datetime:
        return datetime.now(timezone.utc) + timedelta(minutes=poll_interval_minutes)

    @staticmethod
    def _sanitize_job(job: NormalizedJob) -> NormalizedJob:
        description_html, description_text = sanitized_description(
            job.description_html,
            job.description_text,
        )
        return replace(
            job,
            description_html=description_html,
            description_text=description_text,
        )

    @staticmethod
    def _is_due(db: Session, config: SourceConfig) -> bool:
        source = db.scalar(select(Source).where(Source.slug == config.slug))
        if not source or not source.next_due_at:
            return True
        next_due = source.next_due_at
        if next_due.tzinfo is None:
            next_due = next_due.replace(tzinfo=timezone.utc)
        return next_due <= datetime.now(timezone.utc)
