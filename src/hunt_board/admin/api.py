from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from hunt_board.api.schemas import (
    DuplicateReviewRead,
    DuplicateReviewUpdate,
    IngestRunRequest,
    IngestRunResponse,
    OperationsRead,
    ScrapeRunRead,
    ScrapeSourceRunRead,
    SourceRead,
    SourceSyncRead,
    ClassificationOverrideUpdate,
    QuarantineDecision,
    QuarantineRead,
)
from hunt_board.auth.dependencies import require_admin
from hunt_board.core.config import Settings, get_settings
from hunt_board.db.models import (
    DuplicateReview,
    IngestionQuarantine,
    JobLifecycleEvent,
    JobPosting,
    ScrapeRun,
    ScrapeSourceRun,
    Source,
)
from hunt_board.db.session import get_db
from hunt_board.ingestion.registry import sync_sources_from_yaml
from hunt_board.ingestion.lock import IngestionAlreadyRunningError
from hunt_board.ingestion.service import IngestionService
from hunt_board.jobs.classification_service import coverage_report
from hunt_board.core.observability import metrics

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


@router.get("/coverage")
def active_job_coverage(db: Session = Depends(get_db)) -> dict:
    return coverage_report(db)


@router.patch("/jobs/{job_id}/classification")
def override_job_classification(
    job_id: int,
    payload: ClassificationOverrideUpdate,
    user=Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    job = db.get(JobPosting, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    job.job_family_slug = payload.job_family_slug
    job.classification_confidence = 1.0
    job.classification_method = "admin_override"
    job.classification_reason = "Administrator category override"
    job.classification_overridden_at = datetime.now(timezone.utc)
    job.classification_overridden_by_user_id = user.id
    job.classification_override_reason = payload.reason
    db.commit()
    metrics.observe_classification(payload.job_family_slug, "admin_override", "high")
    return {
        "job_id": job.id,
        "job_family_slug": job.job_family_slug,
        "classification_method": job.classification_method,
        "overridden_at": job.classification_overridden_at,
    }


@router.get("/operations", response_model=OperationsRead)
def operations_summary(db: Session = Depends(get_db)) -> dict:
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(hours=24)
    stale_cutoff = now - timedelta(minutes=get_settings().stale_run_minutes)
    recent_runs = list(
        db.scalars(select(ScrapeRun).order_by(ScrapeRun.started_at.desc(), ScrapeRun.id.desc()).limit(10)).all()
    )
    last_run = recent_runs[0] if recent_runs else None
    last_successful_at = db.scalar(
        select(func.max(ScrapeRun.finished_at)).where(ScrapeRun.status == "completed")
    )
    next_due_at = db.scalar(
        select(func.min(Source.next_due_at)).where(Source.enabled.is_(True))
    )
    run_in_progress = bool(
        db.scalar(
            select(func.count(ScrapeRun.id)).where(
                ScrapeRun.status == "running",
                ScrapeRun.started_at >= stale_cutoff,
            )
        )
        or 0
    )
    active_run = db.scalar(
        select(ScrapeRun)
        .where(ScrapeRun.status == "running", ScrapeRun.started_at >= stale_cutoff)
        .order_by(ScrapeRun.started_at.asc())
    )
    pending_run = db.scalar(
        select(ScrapeRun)
        .where(ScrapeRun.status == "pending")
        .order_by(ScrapeRun.created_at.asc())
    )
    source_totals = db.execute(
        select(
            func.count(Source.id),
            func.sum(case((Source.enabled.is_(True), 1), else_=0)),
            func.sum(
                case(
                    (
                        Source.enabled.is_(True)
                        & or_(Source.next_due_at.is_(None), Source.next_due_at <= now),
                        1,
                    ),
                    else_=0,
                )
            ),
            func.sum(
                case((Source.enabled.is_(True) & (Source.health_status == "healthy"), 1), else_=0)
            ),
            func.sum(
                case((Source.enabled.is_(True) & (Source.health_status == "unhealthy"), 1), else_=0)
            ),
        )
    ).one()
    job_totals = db.execute(
        select(
            func.sum(case((JobPosting.active.is_(True), 1), else_=0)),
            func.sum(case((JobPosting.active.is_(False), 1), else_=0)),
            func.sum(case((JobPosting.first_seen_at >= day_ago, 1), else_=0)),
            func.sum(
                case(
                    ((JobPosting.updated_at >= day_ago) & (JobPosting.first_seen_at < day_ago), 1),
                    else_=0,
                )
            ),
        )
    ).one()
    sources = list(db.scalars(select(Source).order_by(Source.enabled.desc(), Source.priority.desc(), Source.company_name)).all())
    return {
        "generated_at": now,
        "ingestion": {
            "run_in_progress": run_in_progress,
            "active_run_id": active_run.id if active_run else None,
            "pending_run_id": pending_run.id if pending_run else None,
            "pending_coalesced_triggers": pending_run.coalesced_triggers if pending_run else 0,
            "last_run": last_run,
            "last_successful_at": last_successful_at,
            "next_due_at": next_due_at,
        },
        "sources": {
            "total": int(source_totals[0] or 0),
            "enabled": int(source_totals[1] or 0),
            "due": int(source_totals[2] or 0),
            "healthy": int(source_totals[3] or 0),
            "unhealthy": int(source_totals[4] or 0),
            "items": [
                {
                    "id": source.id,
                    "slug": source.slug,
                    "name": source.name,
                    "ats": source.ats,
                    "company_name": source.company_name,
                    "company_logo_url": source.company_logo_url,
                    "careers_url": source.careers_url,
                    "enabled": source.enabled,
                    "priority": source.priority,
                    "poll_interval_minutes": source.poll_interval_minutes,
                    "close_after_missed_runs": source.close_after_missed_runs,
                    "categories": source.categories,
                    "notes": source.notes,
                    "health_status": source.health_status,
                    "consecutive_failures": source.consecutive_failures,
                    "last_checked_at": source.last_checked_at,
                    "last_successful_at": source.last_successful_at,
                    "last_error": source.last_error[:300] if source.last_error else None,
                    "next_due_at": source.next_due_at,
                    "last_successful_job_count": source.last_successful_job_count,
                    "quarantine_count": source.quarantine_count,
                }
                for source in sources
            ],
        },
        "jobs": {
            "active": int(job_totals[0] or 0),
            "inactive": int(job_totals[1] or 0),
            "new_last_24_hours": int(job_totals[2] or 0),
            "updated_last_24_hours": int(job_totals[3] or 0),
        },
        "recent_runs": recent_runs,
        "deployment": {
            "environment": get_settings().environment,
            "release": get_settings().release,
            "deployment_id": get_settings().deployment_id,
            "process": get_settings().process_name,
            "web": "healthy",
            "database": "healthy",
        },
        "metrics": _safe_operations_metrics(db, now),
    }


def _safe_operations_metrics(db: Session, now: datetime) -> dict[str, int | float | str | None]:
    day_ago = now - timedelta(hours=24)
    source_duration = db.execute(
        select(func.count(ScrapeSourceRun.id), func.avg(ScrapeSourceRun.duration_ms)).where(
            ScrapeSourceRun.created_at >= day_ago
        )
    ).one()
    source_outcomes = db.execute(
        select(
            func.sum(case((ScrapeSourceRun.status == "completed", 1), else_=0)),
            func.sum(case((ScrapeSourceRun.status == "failed", 1), else_=0)),
            func.sum(case((ScrapeSourceRun.status == "quarantined", 1), else_=0)),
            func.coalesce(func.sum(ScrapeSourceRun.new_jobs), 0),
            func.coalesce(func.sum(ScrapeSourceRun.updated_jobs), 0),
            func.coalesce(func.sum(ScrapeSourceRun.reactivated_jobs), 0),
            func.coalesce(func.sum(ScrapeSourceRun.closed_jobs), 0),
            func.coalesce(func.sum(ScrapeSourceRun.parser_failure_count), 0),
        ).where(ScrapeSourceRun.created_at >= day_ago)
    ).one()
    recent_day_runs = list(
        db.scalars(select(ScrapeRun).where(ScrapeRun.created_at >= day_ago)).all()
    )
    last_success = db.scalar(
        select(func.max(ScrapeRun.finished_at)).where(ScrapeRun.status == "completed")
    )
    return {
        "runs_last_24_hours": int(
            db.scalar(select(func.count(ScrapeRun.id)).where(ScrapeRun.created_at >= day_ago)) or 0
        ),
        "failed_runs_last_24_hours": int(
            db.scalar(
                select(func.count(ScrapeRun.id)).where(
                    ScrapeRun.created_at >= day_ago,
                    ScrapeRun.status.in_({"failed", "abandoned", "completed_with_errors"}),
                )
            ) or 0
        ),
        "quarantines_pending": int(
            db.scalar(
                select(func.count(IngestionQuarantine.id)).where(
                    IngestionQuarantine.status == "pending"
                )
            ) or 0
        ),
        "retries_last_24_hours": int(
            db.scalar(
                select(func.coalesce(func.sum(ScrapeSourceRun.retry_count), 0)).where(
                    ScrapeSourceRun.created_at >= day_ago
                )
            ) or 0
        ),
        "timeouts_last_24_hours": int(
            db.scalar(
                select(func.coalesce(func.sum(ScrapeSourceRun.timeout_count), 0)).where(
                    ScrapeSourceRun.created_at >= day_ago
                )
            ) or 0
        ),
        "source_runs_last_24_hours": int(source_duration[0] or 0),
        "companies_planned_last_24_hours": sum(len(run.sources_requested) for run in recent_day_runs),
        "companies_succeeded_last_24_hours": int(source_outcomes[0] or 0),
        "companies_failed_last_24_hours": int(source_outcomes[1] or 0),
        "companies_quarantined_last_24_hours": int(source_outcomes[2] or 0),
        "jobs_inserted_last_24_hours": int(source_outcomes[3] or 0),
        "jobs_updated_last_24_hours": int(source_outcomes[4] or 0),
        "jobs_reactivated_last_24_hours": int(source_outcomes[5] or 0),
        "jobs_inactivated_last_24_hours": int(source_outcomes[6] or 0),
        "parser_failures_last_24_hours": int(source_outcomes[7] or 0),
        "coalesced_triggers_last_24_hours": sum(run.coalesced_triggers for run in recent_day_runs),
        "average_source_duration_ms": round(float(source_duration[1] or 0), 1),
        "last_successful_scan_at": last_success.isoformat() if last_success else None,
    }


@router.get("/sources", response_model=list[SourceRead])
def list_sources(db: Session = Depends(get_db)) -> list[Source]:
    return list(db.scalars(select(Source).order_by(Source.priority.desc(), Source.company_name)).all())


@router.post("/sources/sync-from-yaml", response_model=SourceSyncRead)
def sync_sources(db: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    try:
        return asdict(sync_sources_from_yaml(db, str(settings.sources_path)))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/ingestion/run", response_model=IngestRunResponse)
async def run_ingestion(payload: IngestRunRequest, db: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    service = _ingestion_service(settings)
    try:
        return asdict(await service.run(db, payload.source_slugs, payload.dry_run, triggered_by="api"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IngestionAlreadyRunningError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/ingestion/run-source/{source_id}", response_model=IngestRunResponse)
async def run_source(source_id: int, dry_run: bool = False, db: Session = Depends(get_db)) -> dict:
    source = db.get(Source, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    settings = get_settings()
    service = _ingestion_service(settings)
    try:
        return asdict(await service.run(db, [source.slug], dry_run, triggered_by="api"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IngestionAlreadyRunningError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _ingestion_service(
    settings: Settings,
    *,
    approved_quarantine_sources: set[str] | None = None,
) -> IngestionService:
    return IngestionService(
        str(settings.sources_path),
        settings.http_timeout_seconds,
        settings.source_concurrency,
        settings.http_max_retries,
        settings.http_retry_backoff_seconds,
        stale_run_minutes=settings.stale_run_minutes,
        retry_jitter_seconds=settings.http_retry_jitter_seconds,
        run_timeout_seconds=settings.run_timeout_seconds,
        anomaly_zero_quarantine=settings.anomaly_zero_quarantine,
        anomaly_volume_change_ratio=settings.anomaly_volume_change_ratio,
        anomaly_mass_change_ratio=settings.anomaly_mass_change_ratio,
        max_job_age_days=settings.max_job_age_days,
        approved_quarantine_sources=approved_quarantine_sources,
        queue_on_contention=True,
    )


@router.get("/scrape-runs", response_model=list[ScrapeRunRead])
def list_scrape_runs(limit: int = Query(default=50, ge=1, le=200), db: Session = Depends(get_db)) -> list[ScrapeRun]:
    return list(db.scalars(select(ScrapeRun).order_by(ScrapeRun.started_at.desc()).limit(limit)).all())


@router.get("/scrape-runs/{run_id}", response_model=ScrapeRunRead)
def get_scrape_run(run_id: int, db: Session = Depends(get_db)) -> ScrapeRun:
    run = db.get(ScrapeRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Scrape run not found")
    return run


@router.get("/scrape-runs/{run_id}/sources", response_model=list[ScrapeSourceRunRead])
def list_scrape_source_runs(run_id: int, db: Session = Depends(get_db)) -> list[ScrapeSourceRun]:
    run = db.get(ScrapeRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Scrape run not found")
    return list(
        db.scalars(
            select(ScrapeSourceRun)
            .where(ScrapeSourceRun.scrape_run_id == run_id)
            .order_by(ScrapeSourceRun.started_at.asc())
        ).all()
    )


@router.get("/scrape-source-runs/{source_run_id}", response_model=ScrapeSourceRunRead)
def get_scrape_source_run(source_run_id: int, db: Session = Depends(get_db)) -> ScrapeSourceRun:
    source_run = db.get(ScrapeSourceRun, source_run_id)
    if source_run is None:
        raise HTTPException(status_code=404, detail="Source run not found")
    return source_run


@router.post("/scrape-runs/{run_id}/retry-failed", response_model=IngestRunResponse)
async def retry_failed_sources(run_id: int, db: Session = Depends(get_db)) -> dict:
    if db.get(ScrapeRun, run_id) is None:
        raise HTTPException(status_code=404, detail="Scrape run not found")
    failed_slugs = list(
        db.scalars(
            select(ScrapeSourceRun.source_slug)
            .where(
                ScrapeSourceRun.scrape_run_id == run_id,
                ScrapeSourceRun.status.in_({"failed", "abandoned"}),
            )
            .distinct()
        ).all()
    )
    if not failed_slugs:
        raise HTTPException(status_code=409, detail="This run has no failed companies to retry")
    return asdict(
        await _ingestion_service(get_settings()).run(
            db, failed_slugs, False, triggered_by="admin_retry"
        )
    )


@router.post("/scrape-runs/{run_id}/cancel")
def cancel_scrape_run(run_id: int, db: Session = Depends(get_db)) -> dict:
    run = db.get(ScrapeRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Scrape run not found")
    if run.status not in {"running", "pending"}:
        raise HTTPException(status_code=409, detail="Only active or pending runs can be cancelled")
    now = datetime.now(timezone.utc)
    run.cancel_requested_at = now
    if run.status == "pending":
        run.status = "cancelled"
        run.cancelled_at = run.finished_at = now
        run.duration_ms = 0
    db.commit()
    metrics.observe_scan_event("cancel", run.status)
    return {"run_id": run.id, "status": run.status, "cancel_requested_at": now}


@router.post("/ingestion/recover-stale")
def recover_stale_runs(db: Session = Depends(get_db)) -> dict:
    recovered = _ingestion_service(get_settings())._recover_stale_runs(db)
    db.commit()
    return {"status": "completed", "recovered_runs": recovered}


@router.get("/quarantines", response_model=list[QuarantineRead])
def list_quarantines(
    status: str | None = Query(default="pending"),
    db: Session = Depends(get_db),
) -> list[IngestionQuarantine]:
    statement = select(IngestionQuarantine).order_by(IngestionQuarantine.created_at.desc())
    if status is not None:
        statement = statement.where(IngestionQuarantine.status == status)
    return list(db.scalars(statement).all())


@router.get("/quarantines/{quarantine_id}", response_model=QuarantineRead)
def get_quarantine(quarantine_id: int, db: Session = Depends(get_db)) -> IngestionQuarantine:
    quarantine = db.get(IngestionQuarantine, quarantine_id)
    if quarantine is None:
        raise HTTPException(status_code=404, detail="Quarantine not found")
    return quarantine


@router.post("/quarantines/{quarantine_id}/reject", response_model=QuarantineRead)
def reject_quarantine(
    quarantine_id: int,
    payload: QuarantineDecision,
    user=Depends(require_admin),
    db: Session = Depends(get_db),
) -> IngestionQuarantine:
    quarantine = db.get(IngestionQuarantine, quarantine_id)
    if quarantine is None:
        raise HTTPException(status_code=404, detail="Quarantine not found")
    if quarantine.status != "pending":
        raise HTTPException(status_code=409, detail="Quarantine was already decided")
    quarantine.status = "rejected"
    quarantine.decided_at = datetime.now(timezone.utc)
    quarantine.decided_by_user_id = user.id
    quarantine.decision_note = payload.note
    source_run = db.get(ScrapeSourceRun, quarantine.scrape_source_run_id)
    if source_run:
        source_run.quarantine_status = "rejected"
    db.commit()
    metrics.observe_scan_event("quarantine", "rejected")
    return quarantine


@router.post("/quarantines/{quarantine_id}/approve", response_model=IngestRunResponse)
async def approve_quarantine(
    quarantine_id: int,
    payload: QuarantineDecision,
    user=Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    quarantine = db.get(IngestionQuarantine, quarantine_id)
    if quarantine is None:
        raise HTTPException(status_code=404, detail="Quarantine not found")
    if quarantine.status != "pending":
        raise HTTPException(status_code=409, detail="Quarantine was already decided")
    quarantine.status = "approved"
    quarantine.decided_at = datetime.now(timezone.utc)
    quarantine.decided_by_user_id = user.id
    quarantine.decision_note = payload.note
    source_run = db.get(ScrapeSourceRun, quarantine.scrape_source_run_id)
    if source_run:
        source_run.quarantine_status = "approved"
    db.commit()
    metrics.observe_scan_event("quarantine", "approved")
    service = _ingestion_service(
        get_settings(), approved_quarantine_sources={quarantine.source_slug}
    )
    return asdict(
        await service.run(
            db, [quarantine.source_slug], False, triggered_by="quarantine_approval"
        )
    )


@router.get("/operations/correlation")
def correlation_lookup(
    identifier: str = Query(min_length=1, max_length=64),
    db: Session = Depends(get_db),
) -> dict:
    runs = list(
        db.scalars(
            select(ScrapeRun).where(
                or_(ScrapeRun.request_id == identifier, ScrapeRun.trace_id == identifier)
            )
        ).all()
    )
    return {
        "identifier": identifier,
        "runs": [
            {
                "run_id": run.id,
                "status": run.status,
                "request_id": run.request_id,
                "trace_id": run.trace_id,
                "started_at": run.started_at,
            }
            for run in runs
        ],
        "lookup_hint": "Search structured logs for the exact request_id or trace_id value.",
    }


@router.post("/jobs/{job_id}/confirm-closed-url")
def confirm_closed_application_url(job_id: int, db: Session = Depends(get_db)) -> dict:
    job = db.get(JobPosting, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.active:
        return {"job_id": job.id, "status": "already_closed"}
    now = datetime.now(timezone.utc)
    job.active = False
    job.closed_at = now
    db.add(
        JobLifecycleEvent(
            job_posting_id=job.id,
            source_id=job.source_id,
            event_type="closed",
            reason="administrator confirmed dead or closed application URL",
            occurred_at=now,
        )
    )
    db.commit()
    return {"job_id": job.id, "status": "closed", "closed_at": now}


@router.get("/duplicates", response_model=list[DuplicateReviewRead])
def list_duplicates(
    status: str | None = Query(default="open"),
    db: Session = Depends(get_db),
) -> list[dict]:
    statement = select(DuplicateReview).order_by(DuplicateReview.created_at.desc())
    if status is not None:
        statement = statement.where(DuplicateReview.status == status)
    return [_duplicate_payload(db, review) for review in db.scalars(statement).all()]


def _duplicate_job_summary(job: JobPosting) -> dict:
    return {
        "id": job.id,
        "title": job.title,
        "company_name": job.company_name,
        "location": job.location,
        "source_slug": job.source_slug,
        "apply_url": job.apply_url,
        "ranking_score": job.ranking_score,
        "first_seen_at": job.first_seen_at,
        "last_seen_at": job.last_seen_at,
        "active": job.active,
        "duplicate_status": job.duplicate_status,
    }


def _duplicate_payload(db: Session, review: DuplicateReview) -> dict:
    candidate = db.get(JobPosting, review.candidate_job_id)
    existing = db.get(JobPosting, review.existing_job_id)
    if candidate is None or existing is None:
        raise HTTPException(status_code=409, detail="Duplicate review references a missing job")
    return {
        "id": review.id,
        "candidate_job_id": review.candidate_job_id,
        "existing_job_id": review.existing_job_id,
        "reason": review.reason,
        "status": review.status,
        "signals_json": review.signals_json,
        "resolution_notes": review.resolution_notes,
        "resolved_at": review.resolved_at,
        "created_at": review.created_at,
        "candidate_job": _duplicate_job_summary(candidate),
        "existing_job": _duplicate_job_summary(existing),
    }


@router.patch("/duplicates/{duplicate_review_id}", response_model=DuplicateReviewRead)
def resolve_duplicate(
    duplicate_review_id: int,
    payload: DuplicateReviewUpdate,
    db: Session = Depends(get_db),
) -> dict:
    review = db.get(DuplicateReview, duplicate_review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Duplicate review not found")
    review.status = payload.status
    review.resolution_notes = payload.resolution_notes
    review.resolved_at = None if payload.status == "open" else datetime.now(timezone.utc)
    candidate = db.get(JobPosting, review.candidate_job_id)
    if candidate and payload.status == "merged":
        candidate.duplicate_status = "duplicate"
        candidate.duplicate_of_job_id = review.existing_job_id
    elif candidate and payload.status == "not_duplicate":
        candidate.duplicate_status = "unique"
        candidate.duplicate_of_job_id = None
    db.commit()
    db.refresh(review)
    return _duplicate_payload(db, review)
