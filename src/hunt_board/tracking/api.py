from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session

from hunt_board.api.schemas import (
    ApplicationCreate,
    ApplicationDeleteResponse,
    ApplicationEventCreate,
    ApplicationEventRead,
    ApplicationRead,
    ApplicationRestoreResponse,
    ApplicationStatusCreate,
    ApplicationStatusRead,
    ApplicationUpdate,
    DiscardedJobDeleteResponse,
    DiscardedJobRead,
    SavedJobCreate,
    SavedJobDeleteResponse,
    SavedJobRead,
    SavedJobUpdate,
    ManualJobCreate,
)
from hunt_board.auth.dependencies import require_user
from hunt_board.db.models import (
    Application,
    ApplicationEvent,
    ApplicationStatus,
    DiscardedJob,
    JobPosting,
    ManualJob,
    SavedJob,
    Source,
    User,
)
from hunt_board.db.session import get_db
from hunt_board.jobs.service import job_summary, source_summary
from hunt_board.core.observability import metrics, trace_span

router = APIRouter(tags=["tracking"])
logger = logging.getLogger("hunt_board")


def _log_application(action: str, application_id: int, user_id: int, *, standard_category: str | None = None) -> None:
    logger.info(
        "application.mutated",
        extra={
            "event_name": "application.mutated",
            "event_data": {
                "action": action,
                "application_id": application_id,
                "user_id": user_id,
                "standard_category": standard_category,
            },
        },
    )


def _resolve_status(
    db: Session, value: str | None, *, default: str = "applied", user_id: int | None = None
) -> ApplicationStatus:
    normalized = (value or default).strip().lower()
    status = db.scalar(
        select(ApplicationStatus).where(
            or_(ApplicationStatus.user_id.is_(None), ApplicationStatus.user_id == user_id),
            or_(func.lower(ApplicationStatus.slug) == normalized, func.lower(ApplicationStatus.name) == normalized)
        )
    )
    if status is None:
        raise HTTPException(status_code=422, detail=f"Unknown application status: {value or default}")
    return status


def _application_payload(
    db: Session,
    application: Application,
    job: JobPosting,
    source: Source | None,
    status: ApplicationStatus | None = None,
    manual_job: ManualJob | None = None,
    *,
    include_events: bool = True,
) -> dict:
    current_status = status
    if current_status is None and application.status_id is not None:
        current_status = db.get(ApplicationStatus, application.status_id)
    if current_status is None:
        current_status = _resolve_status(db, application.status, user_id=application.user_id)
        application.status_id = current_status.id
        application.status = current_status.slug
    events = []
    if include_events:
        events = list(
            db.scalars(
                select(ApplicationEvent)
                .where(ApplicationEvent.application_id == application.id)
                .order_by(ApplicationEvent.occurred_at, ApplicationEvent.id)
            ).all()
        )
    return {
        "id": application.id,
        "notes": application.notes,
        "link_url": application.link_url,
        "deleted_at": application.deleted_at,
        "purge_after": application.purge_after,
        "created_at": application.created_at,
        "updated_at": application.updated_at,
        "status": current_status,
        "job": job_summary(job, source) if job else None,
        "manual_job": manual_job,
        "source": source_summary(source),
        "events": events,
    }


@router.get("/saved-jobs", response_model=list[SavedJobRead])
def list_saved_jobs(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    q: str | None = Query(default=None, max_length=200),
    company: str | None = Query(default=None, max_length=200),
    location: str | None = Query(default=None, max_length=200),
    sort: str = Query(default="recent", pattern="^(recent|score|oldest)$"),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    latest_application_id = (
        select(func.max(Application.id))
        .where(
            Application.job_posting_id == JobPosting.id,
            Application.user_id == user.id,
        )
        .correlate(JobPosting)
        .scalar_subquery()
    )
    application_join = Application.id == latest_application_id
    statement = (
        select(SavedJob, JobPosting, Source, ApplicationStatus)
        .join(JobPosting, JobPosting.id == SavedJob.job_posting_id)
        .join(Source, Source.id == JobPosting.source_id)
        .outerjoin(Application, application_join)
        .outerjoin(ApplicationStatus, ApplicationStatus.id == Application.status_id)
        .where(SavedJob.user_id == user.id)
    )
    if q and (keyword := q.strip()):
        term = f"%{keyword}%"
        statement = statement.where(
            or_(
                JobPosting.title.ilike(term),
                JobPosting.company_name.ilike(term),
                JobPosting.location.ilike(term),
                JobPosting.source_slug.ilike(term),
            )
        )
    if company and (company_term := company.strip()):
        statement = statement.where(JobPosting.company_name.ilike(f"%{company_term}%"))
    if location and (location_term := location.strip()):
        statement = statement.where(JobPosting.location.ilike(f"%{location_term}%"))
    if sort == "score":
        statement = statement.order_by(JobPosting.ranking_score.desc(), SavedJob.created_at.desc(), SavedJob.id.desc())
    elif sort == "oldest":
        statement = statement.order_by(SavedJob.created_at.asc(), SavedJob.id.asc())
    else:
        statement = statement.order_by(SavedJob.created_at.desc(), SavedJob.id.desc())
    rows = db.execute(statement.offset(offset).limit(limit)).all()
    return [
        {
            "id": saved.id,
            "saved_at": saved.created_at,
            "updated_at": saved.updated_at,
            "notes": saved.notes,
            "job": job_summary(job, source),
            "application_status": status,
        }
        for saved, job, source, status in rows
    ]


@router.post("/jobs/{job_id}/save", response_model=SavedJobRead)
def save_job(
    job_id: int,
    payload: SavedJobCreate | None = None,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    job = db.get(JobPosting, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    saved = db.scalar(
        select(SavedJob).where(SavedJob.user_id == user.id, SavedJob.job_posting_id == job_id)
    )
    if saved is None:
        saved = SavedJob(user_id=user.id, job_posting_id=job_id, notes=payload.notes if payload else None)
        db.add(saved)
        db.commit()
        db.refresh(saved)
    status = db.scalar(
        select(ApplicationStatus)
        .join(Application, Application.status_id == ApplicationStatus.id)
        .where(Application.user_id == user.id, Application.job_posting_id == job_id)
        .order_by(Application.id.desc())
        .limit(1)
    )
    source = db.get(Source, job.source_id)
    return {
        "id": saved.id,
        "saved_at": saved.created_at,
        "updated_at": saved.updated_at,
        "notes": saved.notes,
        "job": job_summary(job, source),
        "application_status": status,
    }


@router.delete("/jobs/{job_id}/save", response_model=SavedJobDeleteResponse)
def unsave_job(
    job_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    if db.get(JobPosting, job_id) is None:
        raise HTTPException(status_code=404, detail="Job not found")
    saved = db.scalar(
        select(SavedJob).where(SavedJob.user_id == user.id, SavedJob.job_posting_id == job_id)
    )
    if saved is None:
        return {"job_id": job_id, "removed": False}
    db.delete(saved)
    db.commit()
    return {"job_id": job_id, "removed": True}


@router.get("/discarded-jobs", response_model=list[DiscardedJobRead])
def list_discarded_jobs(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    rows = db.execute(
        select(DiscardedJob, JobPosting, Source)
        .join(JobPosting, JobPosting.id == DiscardedJob.job_posting_id)
        .join(Source, Source.id == JobPosting.source_id)
        .where(DiscardedJob.user_id == user.id)
        .order_by(DiscardedJob.created_at.desc(), DiscardedJob.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return [
        {
            "id": discarded.id,
            "discarded_at": discarded.created_at,
            "job": job_summary(job, source),
        }
        for discarded, job, source in rows
    ]


@router.post("/jobs/{job_id}/discard", response_model=DiscardedJobRead)
def discard_job(
    job_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    job = db.get(JobPosting, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    discarded = db.scalar(
        select(DiscardedJob).where(
            DiscardedJob.user_id == user.id,
            DiscardedJob.job_posting_id == job_id,
        )
    )
    if discarded is None:
        discarded = DiscardedJob(user_id=user.id, job_posting_id=job_id)
        db.add(discarded)
        db.commit()
        db.refresh(discarded)
    source = db.get(Source, job.source_id)
    return {
        "id": discarded.id,
        "discarded_at": discarded.created_at,
        "job": job_summary(job, source),
    }


@router.delete("/jobs/{job_id}/discard", response_model=DiscardedJobDeleteResponse)
def restore_discarded_job(
    job_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    if db.get(JobPosting, job_id) is None:
        raise HTTPException(status_code=404, detail="Job not found")
    discarded = db.scalar(
        select(DiscardedJob).where(
            DiscardedJob.user_id == user.id,
            DiscardedJob.job_posting_id == job_id,
        )
    )
    if discarded is None:
        return {"job_id": job_id, "restored": False}
    db.delete(discarded)
    db.commit()
    return {"job_id": job_id, "restored": True}


@router.patch("/saved-jobs/{saved_job_id}", response_model=SavedJobRead)
def update_saved_job(
    saved_job_id: int,
    payload: SavedJobUpdate,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    saved = db.scalar(select(SavedJob).where(SavedJob.id == saved_job_id, SavedJob.user_id == user.id))
    if saved is None:
        raise HTTPException(status_code=404, detail="Saved job not found")
    if "notes" in payload.model_fields_set:
        saved.notes = payload.notes
    db.commit()
    db.refresh(saved)
    job = db.get(JobPosting, saved.job_posting_id)
    source = db.get(Source, job.source_id) if job else None
    status = db.scalar(
        select(ApplicationStatus)
        .join(Application, Application.status_id == ApplicationStatus.id)
        .where(Application.user_id == user.id, Application.job_posting_id == saved.job_posting_id)
        .order_by(Application.id.desc())
        .limit(1)
    )
    return {
        "id": saved.id,
        "saved_at": saved.created_at,
        "updated_at": saved.updated_at,
        "notes": saved.notes,
        "job": job_summary(job, source),
        "application_status": status,
    }


@router.get("/application-statuses", response_model=list[ApplicationStatusRead])
def list_application_statuses(
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> list[ApplicationStatus]:
    return list(
        db.scalars(
            select(ApplicationStatus)
            .where(or_(ApplicationStatus.user_id.is_(None), ApplicationStatus.user_id == user.id))
            .order_by(ApplicationStatus.sort_order)
        ).all()
    )


@router.post("/application-statuses", response_model=ApplicationStatusRead)
def create_application_status(
    payload: ApplicationStatusCreate,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> ApplicationStatus:
    visible_slug = re.sub(r"[^a-z0-9]+", "-", payload.name.casefold()).strip("-")
    stored_slug = f"u{user.id}-{visible_slug}"
    existing = db.scalar(
        select(ApplicationStatus).where(ApplicationStatus.user_id == user.id, ApplicationStatus.slug == stored_slug)
    )
    if existing:
        raise HTTPException(status_code=409, detail="A custom stage with this name already exists")
    maximum = db.scalar(select(func.max(ApplicationStatus.sort_order))) or 0
    stage = ApplicationStatus(
        user_id=user.id,
        name=payload.name.strip(),
        slug=stored_slug,
        sort_order=maximum + 1,
        is_terminal=payload.standard_category in {"offer", "rejected", "withdrawn", "archived"},
        standard_category=payload.standard_category,
        is_custom=True,
    )
    db.add(stage)
    db.commit()
    db.refresh(stage)
    return stage


@router.get("/applications", response_model=list[ApplicationRead])
def list_applications(
    status: str | None = None,
    terminal: bool | None = None,
    company: str | None = None,
    active_jobs_only: bool = False,
    saved_jobs_only: bool = False,
    recently_deleted: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    statement = (
        select(Application, JobPosting, Source, ApplicationStatus, ManualJob)
        .outerjoin(JobPosting, JobPosting.id == Application.job_posting_id)
        .outerjoin(Source, Source.id == JobPosting.source_id)
        .outerjoin(ApplicationStatus, ApplicationStatus.id == Application.status_id)
        .outerjoin(ManualJob, ManualJob.id == Application.manual_job_id)
        .where(Application.user_id == user.id)
    )
    statement = statement.where(
        Application.deleted_at.is_not(None) if recently_deleted else Application.deleted_at.is_(None)
    )
    if status:
        normalized = status.strip().lower()
        statement = statement.where(
            or_(
                func.lower(ApplicationStatus.slug) == normalized,
                func.lower(ApplicationStatus.name) == normalized,
                func.lower(Application.status) == normalized,
            )
        )
    if terminal is not None:
        statement = statement.where(ApplicationStatus.is_terminal.is_(terminal))
    if company:
        statement = statement.where(
            or_(JobPosting.company_name.ilike(f"%{company.strip()}%"), ManualJob.company_name.ilike(f"%{company.strip()}%"))
        )
    if active_jobs_only:
        statement = statement.where(JobPosting.active.is_(True))
    if saved_jobs_only:
        statement = statement.join(
            SavedJob,
            and_(SavedJob.job_posting_id == JobPosting.id, SavedJob.user_id == user.id),
        )
    rows = db.execute(
        statement.order_by(Application.updated_at.desc(), Application.id.desc()).offset(offset).limit(limit)
    ).all()
    return [
        _application_payload(db, application, job, source, current_status, manual_job, include_events=False)
        for application, job, source, current_status, manual_job in rows
    ]


@router.post("/jobs/{job_id}/applications", response_model=ApplicationRead)
def create_application(
    job_id: int,
    payload: ApplicationCreate | None = None,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    job = db.get(JobPosting, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    source = db.get(Source, job.source_id)
    if payload is None or not payload.create_new:
        existing = db.scalar(
            select(Application)
            .where(
                Application.user_id == user.id,
                Application.job_posting_id == job_id,
                Application.deleted_at.is_(None),
            )
            .order_by(Application.id.desc())
            .limit(1)
        )
        if existing is not None:
            return _application_payload(db, existing, job, source)
    status = _resolve_status(db, payload.status if payload else None, user_id=user.id)
    application = Application(
        user_id=user.id,
        job_posting_id=job_id,
        status_id=status.id,
        status=status.slug,
        notes=payload.notes if payload else None,
        link_url=payload.link_url if payload else None,
    )
    db.add(application)
    db.flush()
    db.add(
        ApplicationEvent(
            application_id=application.id,
            status_id=status.id,
            event_type="status_changed",
            old_status=None,
            new_status=status.slug,
            notes="Application created",
        )
    )
    db.commit()
    db.refresh(application)
    metrics.observe_application("create")
    _log_application("create", application.id, user.id, standard_category=status.standard_category)
    return _application_payload(db, application, job, source, status)


def _application_row(db: Session, application_id: int, user_id: int):
    return db.execute(
        select(Application, JobPosting, Source, ApplicationStatus, ManualJob)
        .outerjoin(JobPosting, JobPosting.id == Application.job_posting_id)
        .outerjoin(Source, Source.id == JobPosting.source_id)
        .outerjoin(ApplicationStatus, ApplicationStatus.id == Application.status_id)
        .outerjoin(ManualJob, ManualJob.id == Application.manual_job_id)
        .where(
            Application.id == application_id,
            Application.user_id == user_id,
            Application.deleted_at.is_(None),
        )
    ).one_or_none()


@router.get("/applications/{application_id}", response_model=ApplicationRead)
def get_application(
    application_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    row = _application_row(db, application_id, user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return _application_payload(db, *row)


@router.patch("/applications/{application_id}", response_model=ApplicationRead)
def update_application(
    application_id: int,
    payload: ApplicationUpdate,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    row = _application_row(db, application_id, user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="Application not found")
    application, job, source, old_status, manual_job = row
    if "notes" in payload.model_fields_set:
        application.notes = payload.notes
    if "link_url" in payload.model_fields_set:
        application.link_url = payload.link_url
    current_status = old_status or _resolve_status(db, application.status, user_id=user.id)
    if "status" in payload.model_fields_set and payload.status is not None:
        new_status = _resolve_status(db, payload.status, user_id=user.id)
        if new_status.id != current_status.id:
            db.add(
                ApplicationEvent(
                    application_id=application.id,
                    status_id=new_status.id,
                    event_type="status_changed",
                    old_status=current_status.slug,
                    new_status=new_status.slug,
                    notes=payload.status_note,
                )
            )
            application.status_id = new_status.id
            application.status = new_status.slug
            current_status = new_status
    db.commit()
    db.refresh(application)
    metrics.observe_application("stage_change" if "status" in payload.model_fields_set else "update")
    _log_application(
        "stage_change" if "status" in payload.model_fields_set else "update",
        application.id,
        user.id,
        standard_category=current_status.standard_category,
    )
    return _application_payload(db, application, job, source, current_status, manual_job)


@router.delete("/applications/{application_id}", response_model=ApplicationDeleteResponse, response_model_exclude_none=True)
def delete_application(
    application_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    application = db.scalar(
        select(Application).where(Application.id == application_id, Application.user_id == user.id)
    )
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    if application.deleted_at is not None:
        return {"application_id": application_id, "job_id": application.job_posting_id, "removed": True}
    application.deleted_at = datetime.now(timezone.utc)
    application.purge_after = application.deleted_at + timedelta(days=30)
    db.commit()
    metrics.observe_application("soft_delete")
    _log_application("soft_delete", application.id, user.id)
    return {"application_id": application_id, "job_id": application.job_posting_id, "removed": True}


@router.post("/applications/{application_id}/restore", response_model=ApplicationRestoreResponse)
def restore_application(
    application_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    application = db.scalar(select(Application).where(Application.id == application_id, Application.user_id == user.id))
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    restored = application.deleted_at is not None
    application.deleted_at = None
    application.purge_after = None
    db.commit()
    metrics.observe_application("restore")
    _log_application("restore", application.id, user.id)
    return {"application_id": application_id, "restored": restored}


@router.delete("/applications/{application_id}/permanent", response_model=ApplicationDeleteResponse)
def permanently_delete_application(
    application_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    application = db.scalar(select(Application).where(Application.id == application_id, Application.user_id == user.id))
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    if application.deleted_at is None:
        raise HTTPException(status_code=409, detail="Move the application to Recently Deleted first")
    job_id = application.job_posting_id
    db.execute(delete(ApplicationEvent).where(ApplicationEvent.application_id == application.id))
    db.delete(application)
    db.commit()
    metrics.observe_application("permanent_delete")
    _log_application("permanent_delete", application_id, user.id)
    return {"application_id": application_id, "job_id": job_id, "removed": True}


@router.post("/manual-jobs", response_model=ApplicationRead)
def create_manual_job(
    payload: ManualJobCreate,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    with trace_span(logger, "manual_job.transaction"):
        status = _resolve_status(db, payload.application_status, user_id=user.id)
        manual = ManualJob(
            user_id=user.id,
            company_name=payload.company_name.strip(),
            title=payload.title.strip(),
            location=payload.location,
            workplace_type=payload.workplace_type,
            job_family_slug=payload.job_family_slug,
            posting_url=payload.posting_url,
            apply_url=payload.apply_url,
            notes=payload.notes,
            approval_status="private",
        )
        db.add(manual)
        db.flush()
        application = Application(
            user_id=user.id,
            manual_job_id=manual.id,
            status_id=status.id,
            status=status.slug,
            notes=payload.application_notes,
            link_url=payload.application_link,
        )
        db.add(application)
        db.flush()
        db.add(ApplicationEvent(application_id=application.id, status_id=status.id, event_type="status_changed", new_status=status.slug, notes="Manual application created"))
        db.commit()
        db.refresh(application)
    metrics.observe_application("manual_job_create")
    logger.info("manual_job.created", extra={"event_name": "manual_job.created", "event_data": {"user_id": user.id, "manual_job_id": manual.id, "application_id": application.id}})
    return _application_payload(db, application, None, None, status, manual)


@router.get("/applications/{application_id}/events", response_model=list[ApplicationEventRead])
def list_application_events(
    application_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> list[ApplicationEvent]:
    application = db.scalar(
        select(Application).where(Application.id == application_id, Application.user_id == user.id, Application.deleted_at.is_(None))
    )
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return list(
        db.scalars(
            select(ApplicationEvent)
            .where(ApplicationEvent.application_id == application_id)
            .order_by(ApplicationEvent.occurred_at, ApplicationEvent.id)
        ).all()
    )


@router.post("/applications/{application_id}/events", response_model=ApplicationEventRead)
def create_application_event(
    application_id: int,
    payload: ApplicationEventCreate,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> ApplicationEvent:
    application = db.scalar(
        select(Application).where(Application.id == application_id, Application.user_id == user.id, Application.deleted_at.is_(None))
    )
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    event = ApplicationEvent(
        application_id=application.id,
        status_id=application.status_id,
        event_type=payload.event_type,
        notes=payload.notes,
        occurred_at=payload.occurred_at or datetime.now(timezone.utc),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event
