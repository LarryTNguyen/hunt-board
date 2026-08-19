from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from time import perf_counter

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from hunt_board.db.models import (
    Application,
    DuplicateReview,
    IngestionQuarantine,
    JobLifecycleEvent,
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
from hunt_board.ingestion.adapters import AdapterFetchResult, ATSAdapter, NormalizedJob, create_adapter
from hunt_board.ingestion.lock import (
    IngestionAlreadyRunningError,
    IngestionRunLock,
    ingestion_lock_for,
)
from hunt_board.ingestion.sanitizer import sanitized_description
from hunt_board.ingestion.sources import SourceConfig, load_sources, select_sources
from hunt_board.jobs.dedupe import DedupeDecision, canonicalize_url, decide_dedupe, normalize_text
from hunt_board.matching.ranking import RankingResult, UserPreferences, rank_job
from hunt_board.jobs.classification import ClassificationResult, apply_classification, classify_job
from hunt_board.core.config import get_settings
from hunt_board.core.observability import (
    metrics,
    request_id_context,
    safe_correlation_id,
    sanitized,
    trace_id_context,
    trace_span,
)


RAW_JSON_RETENTION_DAYS = 7
logger = logging.getLogger(__name__)


class _QuarantinedResult(Exception):
    """Internal control flow: the source result was persisted for admin review."""


@dataclass
class SourceIngestionSummary:
    source_slug: str
    status: str
    fetched_count: int = 0
    upserted_count: int = 0
    new_jobs: int = 0
    updated_jobs: int = 0
    reactivated_jobs: int = 0
    unchanged_jobs: int = 0
    closed_count: int = 0
    duplicates_found: int = 0
    skipped_count: int = 0
    error_count: int = 0
    retry_count: int = 0
    timeout_count: int = 0
    parser_failure_count: int = 0
    quarantine_status: str | None = None
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
    total_reactivated_jobs: int = 0
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
    lifecycle_authoritative: bool = True
    skipped_count: int = 0
    warning_message: str | None = None
    error_message: str | None = None
    retry_count: int = 0
    timeout_count: int = 0
    parser_failure_count: int = 0


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
        retry_jitter_seconds: float = 0.25,
        run_timeout_seconds: int = 3600,
        anomaly_zero_quarantine: bool = True,
        anomaly_volume_change_ratio: float = 0.75,
        anomaly_mass_change_ratio: float = 0.50,
        max_job_age_days: int = 365,
        approved_quarantine_sources: set[str] | None = None,
        queue_on_contention: bool = False,
        minimum_posted_at: datetime | None = None,
    ) -> None:
        self.sources_path = sources_path
        self.timeout_seconds = timeout_seconds
        self.source_concurrency = max(1, source_concurrency)
        self.max_retries = max(0, max_retries)
        self.retry_backoff_seconds = max(0, retry_backoff_seconds)
        self.adapter_overrides = adapter_overrides or {}
        self.run_lock = run_lock
        self.stale_run_minutes = max(5, stale_run_minutes)
        self.retry_jitter_seconds = max(0, retry_jitter_seconds)
        self.run_timeout_seconds = max(60, run_timeout_seconds)
        self.anomaly_zero_quarantine = anomaly_zero_quarantine
        self.anomaly_volume_change_ratio = max(0.1, anomaly_volume_change_ratio)
        self.anomaly_mass_change_ratio = max(0.1, anomaly_mass_change_ratio)
        self.max_job_age_days = max(30, max_job_age_days)
        self.approved_quarantine_sources = approved_quarantine_sources or set()
        self.queue_on_contention = queue_on_contention
        self.minimum_posted_at = minimum_posted_at

    async def run(
        self,
        db: Session,
        requested_slugs: list[str] | None = None,
        dry_run: bool = False,
        triggered_by: str = "api",
    ) -> IngestionSummary:
        if request_id_context.get() is None:
            request_id_context.set(safe_correlation_id(None))
        if trace_id_context.get() is None:
            trace_id_context.set(safe_correlation_id(None))
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
            if not self.queue_on_contention:
                logger.warning("Ingestion run rejected because another real run holds the lock")
                raise IngestionAlreadyRunningError("Another ingestion run is already in progress")
            return self._queue_or_coalesce(
                db,
                summary,
                triggered_by=triggered_by,
                started=started,
            )
        try:
            self._recover_stale_runs(db)
            scrape_run = ScrapeRun(
                status="running",
                dry_run=False,
                triggered_by=triggered_by,
                sources_requested=summary.sources_requested,
                request_id=request_id_context.get(),
                trace_id=trace_id_context.get(),
                environment=get_settings().environment,
                release=get_settings().release,
            )
            db.add(scrape_run)
            db.commit()
            summary.scrape_run_id = scrape_run.id
            logger.info("Ingestion run %s started", scrape_run.id)
            logger.info(
                "scan.run.started",
                extra={
                    "event_name": "scan.run.started",
                    "event_data": {
                        "run_id": scrape_run.id,
                        "trigger": triggered_by,
                        "status": "running",
                        "source_count": len(source_configs),
                    },
                },
            )
            try:
                with trace_span(
                    logger,
                    "scan.run.root.span",
                    run_id=scrape_run.id,
                    trigger=triggered_by,
                    source_count=len(source_configs),
                ):
                    result = await self._execute_run(db, source_configs, summary, scrape_run, started)
                await self._drain_pending(db)
                return result
            except BaseException as exc:
                self._finalize_unexpected_failure(db, scrape_run.id, exc, started)
                if isinstance(exc, Exception):
                    await self._drain_pending(db)
                raise
        finally:
            run_lock.release()

    def _queue_or_coalesce(
        self,
        db: Session,
        summary: IngestionSummary,
        *,
        triggered_by: str,
        started: float,
    ) -> IngestionSummary:
        pending = db.scalar(
            select(ScrapeRun)
            .where(ScrapeRun.status == "pending")
            .order_by(ScrapeRun.created_at.asc(), ScrapeRun.id.asc())
        )
        if pending is not None:
            pending.coalesced_triggers += 1
            db.commit()
            summary.status = "coalesced"
            summary.scrape_run_id = pending.id
            summary.duration_ms = round((perf_counter() - started) * 1000)
            metrics.observe_scan_event("queue", "coalesced")
            logger.info(
                "scan.queue.coalesced",
                extra={
                    "event_name": "scan.queue.coalesced",
                    "event_data": {"run_id": pending.id, "status": summary.status},
                },
            )
            return summary
        pending = ScrapeRun(
            status="pending",
            dry_run=False,
            triggered_by=triggered_by,
            sources_requested=summary.sources_requested,
            request_id=request_id_context.get(),
            trace_id=trace_id_context.get(),
            environment=get_settings().environment,
            release=get_settings().release,
        )
        db.add(pending)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            pending = db.scalar(select(ScrapeRun).where(ScrapeRun.status == "pending"))
            if pending is None:
                raise IngestionAlreadyRunningError("Another ingestion run is already in progress")
            pending.coalesced_triggers += 1
            db.commit()
            summary.status = "coalesced"
        else:
            summary.status = "pending"
        summary.scrape_run_id = pending.id
        summary.duration_ms = round((perf_counter() - started) * 1000)
        metrics.observe_scan_event("queue", summary.status)
        logger.info(
            "scan.queue.updated",
            extra={
                "event_name": "scan.queue.updated",
                "event_data": {"run_id": pending.id, "status": summary.status},
            },
        )
        return summary

    async def _drain_pending(self, db: Session) -> None:
        pending = db.scalar(
            select(ScrapeRun)
            .where(ScrapeRun.status == "pending")
            .order_by(ScrapeRun.created_at.asc(), ScrapeRun.id.asc())
        )
        if pending is None:
            return
        if pending.cancel_requested_at is not None:
            pending.status = "cancelled"
            pending.cancelled_at = pending.finished_at = datetime.now(timezone.utc)
            db.commit()
            return
        configs = select_sources(load_sources(self.sources_path), pending.sources_requested)
        pending.status = "running"
        pending.started_at = datetime.now(timezone.utc)
        db.commit()
        queued_summary = IngestionSummary(
            status="running",
            dry_run=False,
            sources_requested=list(pending.sources_requested),
            scrape_run_id=pending.id,
        )
        await self._execute_run(db, configs, queued_summary, pending, perf_counter())

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
            try:
                fetch_results = await asyncio.wait_for(
                    asyncio.gather(
                        *(self._fetch_source(source, client, semaphore) for source in source_configs)
                    ),
                    timeout=self.run_timeout_seconds,
                )
            except TimeoutError:
                now = datetime.now(timezone.utc)
                fetch_results = [
                    _SourceFetchResult(
                        source=source,
                        started_at=now,
                        finished_at=now,
                        error_message=f"Run exceeded {self.run_timeout_seconds} second timeout",
                        timeout_count=1,
                    )
                    for source in source_configs
                ]
                metrics.observe_scan_event("run", "timeout")
            for fetch_result in fetch_results:
                if scrape_run is not None:
                    db.refresh(scrape_run)
                    if scrape_run.cancel_requested_at is not None:
                        summary.status = "cancelled"
                        break
                source_summary = self._process_source(db, fetch_result, scrape_run, summary.dry_run)
                summary.source_runs.append(source_summary)
                summary.total_fetched += source_summary.fetched_count
                summary.total_upserted += source_summary.upserted_count
                summary.total_new_jobs += source_summary.new_jobs
                summary.total_updated_jobs += source_summary.updated_jobs
                summary.total_reactivated_jobs += source_summary.reactivated_jobs
                summary.total_unchanged_jobs += source_summary.unchanged_jobs
                summary.total_closed += source_summary.closed_count
                summary.total_duplicates += source_summary.duplicates_found
                summary.total_errors += source_summary.error_count

        failed_sources = sum(item.status == "failed" for item in summary.source_runs)
        quarantined_sources = sum(item.status == "quarantined" for item in summary.source_runs)
        degraded_sources = sum(
            item.status == "completed_with_errors" for item in summary.source_runs
        )
        if summary.status == "cancelled":
            pass
        elif failed_sources == len(source_configs) and source_configs:
            summary.status = "failed"
        elif failed_sources or degraded_sources or quarantined_sources:
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
            scrape_run.total_reactivated_jobs = summary.total_reactivated_jobs
            scrape_run.total_unchanged_jobs = summary.total_unchanged_jobs
            scrape_run.total_closed_jobs = summary.total_closed
            scrape_run.total_duplicates = summary.total_duplicates
            # Retain the original aggregate names for existing API clients.
            scrape_run.total_fetched = summary.total_fetched
            scrape_run.total_upserted = summary.total_upserted
            scrape_run.total_closed = summary.total_closed
            scrape_run.total_errors = summary.total_errors
            scrape_run.finished_at = datetime.now(timezone.utc)
            if summary.status == "cancelled":
                scrape_run.cancelled_at = scrape_run.finished_at
            scrape_run.duration_ms = summary.duration_ms
            db.commit()
            metrics.observe_scan_event("run", summary.status)
            logger.info(
                "scan.run.finished",
                extra={
                    "event_name": "scan.run.finished",
                    "event_data": {
                        "run_id": scrape_run.id,
                        "status": summary.status,
                        "duration_ms": summary.duration_ms,
                        "sources_checked": len(summary.source_runs),
                        "jobs_fetched": summary.total_fetched,
                        "jobs_closed": summary.total_closed,
                        "error_count": summary.total_errors,
                    },
                },
            )
            if summary.status == "failed":
                logger.error(
                    "alert.scan.complete_failure",
                    extra={
                        "event_name": "alert.scan.complete_failure",
                        "event_data": {"run_id": scrape_run.id, "status": summary.status},
                    },
                )
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
        message = str(sanitized(f"{type(exc).__name__}: {exc}"))[:4000]
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
                with trace_span(
                    logger,
                    "scan.source.fetch.span",
                    source_slug=source_config.slug,
                    ats=source_config.ats,
                ):
                    adapter_result = await adapter.fetch_jobs(source_config)
                if isinstance(adapter_result, AdapterFetchResult):
                    jobs = adapter_result.jobs
                    lifecycle_authoritative = adapter_result.lifecycle_authoritative
                    skipped_count = adapter_result.skipped_count
                    warning_message = adapter_result.warning_message
                else:
                    jobs = adapter_result
                    lifecycle_authoritative = True
                    skipped_count = 0
                    warning_message = None
                with trace_span(
                    logger,
                    "scan.source.normalize.span",
                    source_slug=source_config.slug,
                    job_count=len(jobs),
                ):
                    jobs = [self._sanitize_job(job) for job in jobs]
                if self.minimum_posted_at is not None:
                    jobs = [
                        job
                        for job in jobs
                        if job.posted_at is None
                        or self._comparable_datetime(job.posted_at) >= self.minimum_posted_at
                    ]
                retry_count = int(getattr(adapter, "retry_count", 0))
                timeout_count = int(getattr(adapter, "timeout_count", 0))
            return _SourceFetchResult(
                source=source_config,
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                jobs=jobs,
                lifecycle_authoritative=lifecycle_authoritative,
                skipped_count=skipped_count,
                warning_message=warning_message,
                retry_count=retry_count,
                timeout_count=timeout_count,
            )
        except Exception as exc:  # each fetch is isolated so other sources can finish
            message = str(sanitized(str(exc)))
            return _SourceFetchResult(
                source=source_config,
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                error_message=message,
                retry_count=int(getattr(locals().get("adapter"), "retry_count", 0)),
                timeout_count=int(getattr(locals().get("adapter"), "timeout_count", 0)),
                parser_failure_count=int(
                    any(token in message.casefold() for token in ("parse", "malformed", "expected json", "decode"))
                ),
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
            skipped_count=fetch_result.skipped_count,
            error_count=fetch_result.skipped_count,
            error_message=fetch_result.warning_message,
            retry_count=fetch_result.retry_count,
            timeout_count=fetch_result.timeout_count,
            parser_failure_count=fetch_result.parser_failure_count,
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
            active_source_jobs = self._active_source_jobs(db, source_row)
            active_by_external_id = {
                job.external_job_id: job
                for job in active_source_jobs
                if job.external_job_id is not None
            }
            anomaly = self._anomaly_summary(
                source_row,
                fetch_result,
                active_source_jobs,
            )
            if anomaly is not None and source_config.slug not in self.approved_quarantine_sources:
                source_summary.status = "quarantined"
                source_summary.quarantine_status = "pending"
                source_summary.error_count = 0
                source_summary.error_message = anomaly[0]
                if not dry_run and source_row is not None and source_run is not None:
                    quarantine = IngestionQuarantine(
                        scrape_run_id=scrape_run.id,
                        scrape_source_run_id=source_run.id,
                        source_id=source_row.id,
                        source_slug=source_row.slug,
                        reason=anomaly[0],
                        diff_summary=anomaly[1],
                        observed_external_ids=sorted(
                            {job.external_job_id for job in fetch_result.jobs}
                        ),
                    )
                    db.add(quarantine)
                    source_row.health_status = "quarantined"
                    source_row.quarantine_count += 1
                    source_row.next_due_at = self._next_due(
                        source_config.effective_poll_interval_minutes
                    )
                    db.flush()
                    metrics.observe_scan_event("quarantine", "created")
                    logger.warning(
                        "scan.source.quarantined",
                        extra={
                            "event_name": "scan.source.quarantined",
                            "event_data": {
                                "run_id": scrape_run.id,
                                "source_id": source_row.id,
                                "source_slug": source_row.slug,
                                "status": "quarantined",
                                "reason": anomaly[0],
                                **anomaly[1],
                            },
                        },
                    )
                    logger.warning(
                        "alert.scan.quarantine",
                        extra={
                            "event_name": "alert.scan.quarantine",
                            "event_data": {
                                "run_id": scrape_run.id,
                                "source_slug": source_row.slug,
                                "status": "quarantined",
                            },
                        },
                    )
                raise _QuarantinedResult
            with db.begin_nested():
                seen_external_ids = {
                    job.external_job_id for job in fetch_result.jobs if not job.explicitly_closed
                }
                preferences = self._preferences(db)
                for job in fetch_result.jobs:
                    if job.explicitly_closed:
                        if not dry_run and source_row:
                            source_summary.closed_count += self._close_explicit_job(
                                db, source_row, job.external_job_id, scrape_run
                            )
                        continue
                    ranking = rank_job(job, preferences, source_config.priority)
                    with trace_span(
                        logger,
                        "scan.job.dedupe.span",
                        source_slug=source_config.slug,
                    ):
                        decision = decide_dedupe(
                            db,
                            source_row,
                            job,
                            active_by_external_id=active_by_external_id,
                        )
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
                        with trace_span(
                            logger,
                            "scan.job.upsert.span",
                            source_slug=source_config.slug,
                        ):
                            outcome, duplicate_found, reactivated = self._upsert_job(
                                db, source_row, job, ranking, decision, scrape_run
                            )
                        if outcome == "new":
                            source_summary.new_jobs += 1
                        elif outcome == "updated":
                            source_summary.updated_jobs += 1
                        else:
                            source_summary.unchanged_jobs += 1
                        source_summary.duplicates_found += int(duplicate_found)
                        source_summary.reactivated_jobs += int(reactivated)
                    if outcome != "unchanged":
                        source_summary.upserted_count += 1
                if not dry_run and source_row and fetch_result.lifecycle_authoritative:
                    with trace_span(
                        logger,
                        "scan.source.reconcile.span",
                        source_slug=source_config.slug,
                        observed_count=len(seen_external_ids),
                    ):
                        source_summary.closed_count += self._mark_closed(
                            db,
                            source_row,
                            seen_external_ids,
                            source_config.close_after_missed_runs,
                            scrape_run,
                            self.max_job_age_days,
                            active_jobs=active_source_jobs,
                        )
            source_summary.status = (
                "completed"
                if fetch_result.lifecycle_authoritative
                else "completed_with_errors"
            )
            if source_row and not dry_run:
                if fetch_result.lifecycle_authoritative:
                    source_row.health_status = "healthy"
                    source_row.consecutive_failures = 0
                    source_row.last_successful_at = datetime.now(timezone.utc)
                    source_row.last_successful_job_count = len(fetch_result.jobs)
                    source_row.last_error = None
                else:
                    source_row.health_status = "unhealthy"
                    source_row.consecutive_failures += 1
                    source_row.last_error = fetch_result.warning_message
                source_row.next_due_at = self._next_due(source_config.effective_poll_interval_minutes)
        except _QuarantinedResult:
            pass
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
                if source_row.consecutive_failures >= 3:
                    logger.error(
                        "alert.source.repeated_failure",
                        extra={
                            "event_name": "alert.source.repeated_failure",
                            "event_data": {
                                "run_id": scrape_run.id if scrape_run else None,
                                "source_slug": source_row.slug,
                                "status": "unhealthy",
                                "consecutive_failures": source_row.consecutive_failures,
                            },
                        },
                    )
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
            source_run.reactivated_jobs = source_summary.reactivated_jobs
            source_run.unchanged_jobs = source_summary.unchanged_jobs
            source_run.closed_jobs = source_summary.closed_count
            source_run.duplicates_found = source_summary.duplicates_found
            source_run.fetched_count = source_summary.fetched_count
            source_run.upserted_count = source_summary.upserted_count
            source_run.closed_count = source_summary.closed_count
            source_run.error_count = source_summary.error_count
            source_run.retry_count = source_summary.retry_count
            source_run.timeout_count = source_summary.timeout_count
            source_run.parser_failure_count = source_summary.parser_failure_count
            source_run.quarantine_status = source_summary.quarantine_status
            source_run.trace_id = scrape_run.trace_id if scrape_run else trace_id_context.get()
            source_run.error_message = source_summary.error_message
            source_run.finished_at = finished_at
            source_run.duration_ms = source_summary.duration_ms
            db.flush()
        logger.info(
            "Ingestion source %s finished with status %s",
            source_config.slug,
            source_summary.status,
        )
        if source_summary.retry_count:
            metrics.observe_scan_event("retry", "attempted")
        if source_summary.timeout_count:
            metrics.observe_scan_event("timeout", "source")
        logger.info(
            "scan.source.finished",
            extra={
                "event_name": "scan.source.finished",
                "event_data": {
                    "run_id": scrape_run.id if scrape_run else None,
                    "source_id": source_row.id if source_row else None,
                    "source_slug": source_config.slug,
                    "status": source_summary.status,
                    "duration_ms": source_summary.duration_ms,
                    "retry_count": source_summary.retry_count,
                    "timeout_count": source_summary.timeout_count,
                    "fetched_count": source_summary.fetched_count,
                    "closed_count": source_summary.closed_count,
                },
            },
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
            retry_jitter_seconds=self.retry_jitter_seconds,
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
        # Shared catalog scores must not inherit an arbitrary user's private
        # preferences. Per-profile rankings are persisted in job_matches.
        return UserPreferences()

    def _upsert_job(
        self,
        db: Session,
        source: Source,
        job: NormalizedJob,
        ranking: RankingResult,
        decision: DedupeDecision,
        scrape_run: ScrapeRun | None,
    ) -> tuple[str, bool, bool]:
        now = datetime.now(timezone.utc)
        try:
            classification = classify_job(
                department=job.department,
                title=job.title,
                description=job.description_text,
            )
        except Exception:
            logger.exception(
                "classification.error",
                extra={"event_name": "classification.error", "event_data": {"source_slug": source.slug}},
            )
            classification = ClassificationResult("other", 0.0, "error", "Classification failed safely")
        target = decision.existing_job if decision.action == "upsert" else None
        if (
            target is not None
            and not decision.reactivated
            and not self._job_changed(target, job, ranking)
        ):
            # The normalized posting is unchanged; only observation metadata must move.
            target.last_seen_at = now
            target.consecutive_missed_runs = 0
            db.flush()
            return "unchanged", False, False
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
                locations_json=self._structured_locations(job),
                raw_json=job.raw_json,
            )
            db.add(target)
            db.flush()
        elif decision.reactivated:
            target.reposted_at = now
            db.add(
                JobLifecycleEvent(
                    job_posting_id=target.id,
                    source_id=source.id,
                    scrape_run_id=scrape_run.id if scrape_run else None,
                    event_type="reactivated",
                    reason="same stable job identity reappeared",
                    occurred_at=now,
                )
            )

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
        target.locations_json = self._structured_locations(job)
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
        target.posted_at = job.posted_at
        target.source_updated_at = job.updated_at
        target.ranking_score = ranking.score
        target.ranking_reasons = ranking.reasons
        apply_classification(target, classification)
        workplace = (job.workplace_type or "").casefold()
        target.remote_scope = (
            "country_restricted"
            if "remote" in workplace and job.location_country_code
            else "unrestricted"
            if "remote" in workplace
            else "not_remote"
        )
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
        self._record_user_results(
            db,
            target,
            job,
            source.priority,
            outcome=outcome,
            reactivated=decision.reactivated,
            changed_version=version if outcome == "updated" else None,
            scrape_run=scrape_run,
        )
        db.flush()
        return outcome, duplicate_found, decision.reactivated

    @classmethod
    def _job_changed(
        cls,
        target: JobPosting,
        job: NormalizedJob,
        ranking: RankingResult,
    ) -> bool:
        location = cls._display_location(job)
        expected_posted_at = job.posted_at
        relevant_values = (
            (target.company_name, job.company_name),
            (target.title, job.title),
            (target.normalized_title, normalize_text(job.title) or ""),
            (target.location, location),
            (target.normalized_location, normalize_text(location)),
            (target.location_country_code, job.location_country_code),
            (target.location_country, job.location_country),
            (target.locations_json, cls._structured_locations(job)),
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
            (target.description_hash, cls._description_hash(job)),
            (cls._comparable_datetime(target.posted_at), cls._comparable_datetime(expected_posted_at)),
            (cls._comparable_datetime(target.source_updated_at), cls._comparable_datetime(job.updated_at)),
            (target.ranking_score, ranking.score),
            (target.ranking_reasons, ranking.reasons),
        )
        if target.classification_overridden_at is None:
            classification = classify_job(
                department=job.department,
                title=job.title,
                description=job.description_text,
            )
            relevant_values += (
                (target.job_family_slug, classification.family_slug),
                (target.classification_method, classification.method),
                (target.classification_reason, classification.reason),
            )
        return not target.active or any(current != incoming for current, incoming in relevant_values)

    @staticmethod
    def _comparable_datetime(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _record_version(db: Session, target: JobPosting, job: NormalizedJob) -> JobVersion | None:
        description_hash = IngestionService._description_hash(job)
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
                raw_json={},
                raw_json_expires_at=None,
            )
            db.add(existing_version)
            db.flush()
        return existing_version

    @staticmethod
    def _description_hash(job: NormalizedJob) -> str:
        description = job.description_text or job.description_html or ""
        return hashlib.sha256(description.encode("utf-8")).hexdigest()

    @staticmethod
    def _user_preferences(db: Session, user: User) -> UserPreferences:
        preference = db.scalar(
            select(UserPreference).where(UserPreference.user_id == user.id)
        )
        if preference is None:
            return UserPreferences.model_validate(user.preferences_json or {})
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

    @classmethod
    def _record_user_results(
        cls,
        db: Session,
        job: JobPosting,
        normalized_job: NormalizedJob,
        source_priority: int,
        *,
        outcome: str,
        reactivated: bool,
        changed_version: JobVersion | None,
        scrape_run: ScrapeRun | None,
    ) -> None:
        users = db.scalars(
            select(User)
            .where(
                User.is_active.is_(True),
                User.account_status == "active",
                User.deleted_at.is_(None),
            )
            .order_by(User.id)
        ).all()
        for user in users:
            preferences = cls._user_preferences(db, user)
            ranking = rank_job(normalized_job, preferences, source_priority)
            cls._record_match(db, job, user, ranking)
            cls._record_notifications(
                db,
                job,
                user,
                preferences,
                ranking,
                outcome=outcome,
                reactivated=reactivated,
                changed_version=changed_version,
                scrape_run=scrape_run,
            )

    @classmethod
    def _record_notifications(
        cls,
        db: Session,
        job: JobPosting,
        user: User,
        preferences: UserPreferences,
        ranking: RankingResult,
        *,
        outcome: str,
        reactivated: bool,
        changed_version: JobVersion | None,
        scrape_run: ScrapeRun | None,
    ) -> None:
        threshold = preferences.minimum_score_threshold
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
                ranking_score=ranking.score,
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
                ranking_score=ranking.score,
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
                    ranking_score=ranking.score,
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
        ranking_score: float,
    ) -> None:
        if db.scalar(
            select(Notification.id).where(
                Notification.user_id == user_id,
                Notification.dedupe_key == dedupe_key,
            )
        ) is not None:
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
                    "ranking_score": ranking_score,
                    "message": message,
                },
            )
        )

    @staticmethod
    def _record_match(
        db: Session,
        target: JobPosting,
        user: User,
        ranking: RankingResult,
    ) -> None:
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
    def _active_source_jobs(db: Session, source: Source | None) -> list[JobPosting]:
        if source is None:
            return []
        return list(
            db.scalars(
                select(JobPosting)
                .where(
                    JobPosting.source_id == source.id,
                    JobPosting.active.is_(True),
                )
            ).all()
        )

    def _anomaly_summary(
        self,
        source: Source | None,
        fetch_result: _SourceFetchResult,
        existing: list[JobPosting],
    ) -> tuple[str, dict[str, int | float]] | None:
        if source is None or not fetch_result.lifecycle_authoritative:
            return None
        current_count = len(fetch_result.jobs)
        baseline = source.last_successful_job_count
        if baseline is None:
            baseline = len(existing)
        if baseline < 5:
            return None
        observed_ids = {job.external_job_id for job in fetch_result.jobs}
        absent_count = sum(job.external_job_id not in observed_ids for job in existing)
        volume_change = abs(current_count - baseline) / max(1, baseline)
        changed_count = 0
        existing_by_id = {job.external_job_id: job for job in existing}
        overlap_count = 0
        for job in fetch_result.jobs:
            prior = existing_by_id.get(job.external_job_id)
            if prior is None:
                continue
            overlap_count += 1
            if (
                prior.normalized_title != (normalize_text(job.title) or "")
                or prior.normalized_location != normalize_text(self._display_location(job))
            ):
                changed_count += 1
        changed_ratio = changed_count / max(1, overlap_count)
        deactivation_ratio = absent_count / max(1, len(existing))
        summary: dict[str, int | float] = {
            "baseline_count": baseline,
            "fetched_count": current_count,
            "active_count": len(existing),
            "absent_count": absent_count,
            "volume_change_ratio": round(volume_change, 4),
            "changed_title_location_count": changed_count,
            "changed_title_location_ratio": round(changed_ratio, 4),
            "attempted_deactivation_ratio": round(deactivation_ratio, 4),
        }
        if self.anomaly_zero_quarantine and current_count == 0:
            return "Suspicious zero-result scan", summary
        if volume_change >= self.anomaly_volume_change_ratio:
            return "Suspicious source volume change", summary
        if overlap_count >= 5 and changed_ratio >= self.anomaly_mass_change_ratio:
            return "Suspicious mass title/location change", summary
        if deactivation_ratio >= self.anomaly_mass_change_ratio:
            return "Suspicious mass deactivation attempt", summary
        return None

    @staticmethod
    def _close_explicit_job(
        db: Session,
        source: Source,
        external_job_id: str,
        scrape_run: ScrapeRun | None,
    ) -> int:
        job = db.scalar(
            select(JobPosting).where(
                JobPosting.source_id == source.id,
                JobPosting.external_job_id == external_job_id,
                JobPosting.active.is_(True),
            )
        )
        if job is None:
            return 0
        now = datetime.now(timezone.utc)
        job.active = False
        job.closed_at = now
        db.add(
            JobLifecycleEvent(
                job_posting_id=job.id,
                source_id=source.id,
                scrape_run_id=scrape_run.id if scrape_run else None,
                event_type="closed",
                reason="source explicitly reported closed",
                occurred_at=now,
            )
        )
        return 1

    def _mark_closed(
        self,
        db: Session,
        source: Source,
        seen_external_ids: set[str],
        close_after_missed_runs: int,
        scrape_run: ScrapeRun | None = None,
        max_job_age_days: int = 365,
        *,
        active_jobs: list[JobPosting] | None = None,
    ) -> int:
        if active_jobs is None:
            active_jobs = self._active_source_jobs(db, source)
        now = datetime.now(timezone.utc)
        closed_count = 0
        for job in active_jobs:
            first_seen = job.first_seen_at
            if first_seen.tzinfo is None:
                first_seen = first_seen.replace(tzinfo=timezone.utc)
            closure_reason: str | None = None
            if first_seen <= now - timedelta(days=max_job_age_days):
                closure_reason = f"maximum age of {max_job_age_days} days reached"
            if job.external_job_id in seen_external_ids:
                job.consecutive_missed_runs = 0
                if closure_reason is None:
                    continue
            else:
                job.consecutive_missed_runs += 1
                if job.consecutive_missed_runs >= close_after_missed_runs:
                    closure_reason = f"absent from {close_after_missed_runs} successful scans"
            if closure_reason is not None:
                job.active = False
                job.closed_at = now
                closed_count += 1
                db.add(
                    JobLifecycleEvent(
                        job_posting_id=job.id,
                        source_id=source.id,
                        scrape_run_id=scrape_run.id if scrape_run else None,
                        event_type="closed",
                        reason=closure_reason,
                        occurred_at=now,
                    )
                )
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

    @classmethod
    def _structured_locations(cls, job: NormalizedJob) -> list[dict[str, object]]:
        if job.locations:
            return job.locations
        display = cls._display_location(job)
        if not display:
            return []
        return [
            {
                "display": display,
                "country_code": job.location_country_code,
                "country": job.location_country,
                "is_primary": True,
            }
        ]

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
