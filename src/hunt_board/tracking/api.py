from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from hunt_board.api.schemas import (
    ApplicationCreate,
    ApplicationEventCreate,
    ApplicationEventRead,
    ApplicationRead,
    ApplicationStatusRead,
    ApplicationUpdate,
    DiscardedJobDeleteResponse,
    DiscardedJobRead,
    SavedJobCreate,
    SavedJobDeleteResponse,
    SavedJobRead,
    SavedJobUpdate,
)
from hunt_board.auth.single_user import get_single_user
from hunt_board.db.models import (
    Application,
    ApplicationEvent,
    ApplicationStatus,
    DiscardedJob,
    JobPosting,
    SavedJob,
    Source,
)
from hunt_board.db.session import get_db
from hunt_board.jobs.service import job_summary, source_summary

router = APIRouter(tags=["tracking"])


def _resolve_status(db: Session, value: str | None, *, default: str = "applied") -> ApplicationStatus:
    normalized = (value or default).strip().lower()
    status = db.scalar(
        select(ApplicationStatus).where(
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
    *,
    include_events: bool = True,
) -> dict:
    current_status = status
    if current_status is None and application.status_id is not None:
        current_status = db.get(ApplicationStatus, application.status_id)
    if current_status is None:
        current_status = _resolve_status(db, application.status)
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
        "created_at": application.created_at,
        "updated_at": application.updated_at,
        "status": current_status,
        "job": job_summary(job),
        "source": source_summary(source),
        "events": events,
    }


@router.get("/saved-jobs", response_model=list[SavedJobRead])
def list_saved_jobs(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[dict]:
    user = get_single_user(db)
    application_join = and_(
        Application.job_posting_id == JobPosting.id,
        Application.user_id == user.id,
    )
    rows = db.execute(
        select(SavedJob, JobPosting, ApplicationStatus)
        .join(JobPosting, JobPosting.id == SavedJob.job_posting_id)
        .outerjoin(Application, application_join)
        .outerjoin(ApplicationStatus, ApplicationStatus.id == Application.status_id)
        .where(SavedJob.user_id == user.id)
        .order_by(SavedJob.created_at.desc(), SavedJob.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return [
        {
            "id": saved.id,
            "saved_at": saved.created_at,
            "updated_at": saved.updated_at,
            "notes": saved.notes,
            "job": job_summary(job),
            "application_status": status,
        }
        for saved, job, status in rows
    ]


@router.post("/jobs/{job_id}/save", response_model=SavedJobRead)
def save_job(
    job_id: int,
    payload: SavedJobCreate | None = None,
    db: Session = Depends(get_db),
) -> dict:
    user = get_single_user(db)
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
    )
    return {
        "id": saved.id,
        "saved_at": saved.created_at,
        "updated_at": saved.updated_at,
        "notes": saved.notes,
        "job": job_summary(job),
        "application_status": status,
    }


@router.delete("/jobs/{job_id}/save", response_model=SavedJobDeleteResponse)
def unsave_job(job_id: int, db: Session = Depends(get_db)) -> dict:
    user = get_single_user(db)
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
    db: Session = Depends(get_db),
) -> list[dict]:
    user = get_single_user(db)
    rows = db.execute(
        select(DiscardedJob, JobPosting)
        .join(JobPosting, JobPosting.id == DiscardedJob.job_posting_id)
        .where(DiscardedJob.user_id == user.id)
        .order_by(DiscardedJob.created_at.desc(), DiscardedJob.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return [
        {
            "id": discarded.id,
            "discarded_at": discarded.created_at,
            "job": job_summary(job),
        }
        for discarded, job in rows
    ]


@router.post("/jobs/{job_id}/discard", response_model=DiscardedJobRead)
def discard_job(job_id: int, db: Session = Depends(get_db)) -> dict:
    user = get_single_user(db)
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
    return {
        "id": discarded.id,
        "discarded_at": discarded.created_at,
        "job": job_summary(job),
    }


@router.delete("/jobs/{job_id}/discard", response_model=DiscardedJobDeleteResponse)
def restore_discarded_job(job_id: int, db: Session = Depends(get_db)) -> dict:
    user = get_single_user(db)
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
def update_saved_job(saved_job_id: int, payload: SavedJobUpdate, db: Session = Depends(get_db)) -> dict:
    user = get_single_user(db)
    saved = db.scalar(select(SavedJob).where(SavedJob.id == saved_job_id, SavedJob.user_id == user.id))
    if saved is None:
        raise HTTPException(status_code=404, detail="Saved job not found")
    if "notes" in payload.model_fields_set:
        saved.notes = payload.notes
    db.commit()
    db.refresh(saved)
    job = db.get(JobPosting, saved.job_posting_id)
    status = db.scalar(
        select(ApplicationStatus)
        .join(Application, Application.status_id == ApplicationStatus.id)
        .where(Application.user_id == user.id, Application.job_posting_id == saved.job_posting_id)
    )
    return {
        "id": saved.id,
        "saved_at": saved.created_at,
        "updated_at": saved.updated_at,
        "notes": saved.notes,
        "job": job_summary(job),
        "application_status": status,
    }


@router.get("/application-statuses", response_model=list[ApplicationStatusRead])
def list_application_statuses(db: Session = Depends(get_db)) -> list[ApplicationStatus]:
    return list(db.scalars(select(ApplicationStatus).order_by(ApplicationStatus.sort_order)).all())


@router.get("/applications", response_model=list[ApplicationRead])
def list_applications(
    status: str | None = None,
    terminal: bool | None = None,
    company: str | None = None,
    active_jobs_only: bool = False,
    saved_jobs_only: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[dict]:
    user = get_single_user(db)
    statement = (
        select(Application, JobPosting, Source, ApplicationStatus)
        .join(JobPosting, JobPosting.id == Application.job_posting_id)
        .join(Source, Source.id == JobPosting.source_id)
        .outerjoin(ApplicationStatus, ApplicationStatus.id == Application.status_id)
        .where(Application.user_id == user.id)
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
        statement = statement.where(JobPosting.company_name.ilike(f"%{company.strip()}%"))
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
        _application_payload(db, application, job, source, current_status, include_events=False)
        for application, job, source, current_status in rows
    ]


@router.post("/jobs/{job_id}/applications", response_model=ApplicationRead)
def create_application(
    job_id: int,
    payload: ApplicationCreate | None = None,
    db: Session = Depends(get_db),
) -> dict:
    user = get_single_user(db)
    job = db.get(JobPosting, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    existing = db.scalar(
        select(Application).where(Application.user_id == user.id, Application.job_posting_id == job_id)
    )
    source = db.get(Source, job.source_id)
    if existing is not None:
        return _application_payload(db, existing, job, source)

    status = _resolve_status(db, payload.status if payload else None)
    application = Application(
        user_id=user.id,
        job_posting_id=job_id,
        status_id=status.id,
        status=status.slug,
        notes=payload.notes if payload else None,
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
    return _application_payload(db, application, job, source, status)


def _application_row(db: Session, application_id: int, user_id: int):
    return db.execute(
        select(Application, JobPosting, Source, ApplicationStatus)
        .join(JobPosting, JobPosting.id == Application.job_posting_id)
        .join(Source, Source.id == JobPosting.source_id)
        .outerjoin(ApplicationStatus, ApplicationStatus.id == Application.status_id)
        .where(Application.id == application_id, Application.user_id == user_id)
    ).one_or_none()


@router.get("/applications/{application_id}", response_model=ApplicationRead)
def get_application(application_id: int, db: Session = Depends(get_db)) -> dict:
    user = get_single_user(db)
    row = _application_row(db, application_id, user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return _application_payload(db, *row)


@router.patch("/applications/{application_id}", response_model=ApplicationRead)
def update_application(application_id: int, payload: ApplicationUpdate, db: Session = Depends(get_db)) -> dict:
    user = get_single_user(db)
    row = _application_row(db, application_id, user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="Application not found")
    application, job, source, old_status = row
    if "notes" in payload.model_fields_set:
        application.notes = payload.notes
    current_status = old_status or _resolve_status(db, application.status)
    if "status" in payload.model_fields_set and payload.status is not None:
        new_status = _resolve_status(db, payload.status)
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
    return _application_payload(db, application, job, source, current_status)


@router.get("/applications/{application_id}/events", response_model=list[ApplicationEventRead])
def list_application_events(application_id: int, db: Session = Depends(get_db)) -> list[ApplicationEvent]:
    user = get_single_user(db)
    application = db.scalar(
        select(Application).where(Application.id == application_id, Application.user_id == user.id)
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
    db: Session = Depends(get_db),
) -> ApplicationEvent:
    user = get_single_user(db)
    application = db.scalar(
        select(Application).where(Application.id == application_id, Application.user_id == user.id)
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
