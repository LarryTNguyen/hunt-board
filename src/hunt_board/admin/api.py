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
)
from hunt_board.core.config import Settings, get_settings
from hunt_board.db.models import DuplicateReview, JobPosting, ScrapeRun, ScrapeSourceRun, Source
from hunt_board.db.session import get_db
from hunt_board.ingestion.registry import sync_sources_from_yaml
from hunt_board.ingestion.lock import IngestionAlreadyRunningError
from hunt_board.ingestion.service import IngestionService

router = APIRouter(prefix="/admin", tags=["admin"])


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


def _ingestion_service(settings: Settings) -> IngestionService:
    return IngestionService(
        str(settings.sources_path),
        settings.http_timeout_seconds,
        settings.source_concurrency,
        settings.http_max_retries,
        settings.http_retry_backoff_seconds,
        stale_run_minutes=settings.stale_run_minutes,
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
