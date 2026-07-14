from __future__ import annotations

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from hunt_board.db.models import Application, ApplicationStatus, JobPosting, SavedJob, Source


def source_summary(source: Source | None) -> dict | None:
    if source is None:
        return None
    return {
        "id": source.id,
        "slug": source.slug,
        "name": source.name,
        "ats": source.ats,
        "company_name": source.company_name,
    }


def job_summary(job: JobPosting) -> dict:
    return {
        "id": job.id,
        "title": job.title,
        "company_name": job.company_name,
        "location": job.location,
        "apply_url": job.apply_url,
        "ranking_score": job.ranking_score,
        "active": job.active,
        "duplicate_status": job.duplicate_status,
        "duplicate_of_job_id": job.duplicate_of_job_id,
        "reposted_at": job.reposted_at,
    }


def job_read_payload(
    job: JobPosting,
    source: Source | None,
    saved_job_id: int | None,
    application_id: int | None,
    application_status: ApplicationStatus | None,
) -> dict:
    return {
        "id": job.id,
        "source_id": job.source_id,
        "source_slug": job.source_slug,
        "source": source_summary(source),
        "company_name": job.company_name,
        "external_job_id": job.external_job_id,
        "title": job.title,
        "location": job.location,
        "department": job.department,
        "employment_type": job.employment_type,
        "workplace_type": job.workplace_type,
        "posting_url": job.posting_url,
        "apply_url": job.apply_url,
        "description_html": job.description_html,
        "description_text": job.description_text,
        "active": job.active,
        "duplicate_status": job.duplicate_status,
        "duplicate_of_job_id": job.duplicate_of_job_id,
        "is_duplicate": job.duplicate_status == "duplicate",
        "reposted_at": job.reposted_at,
        "is_reposted": job.reposted_at is not None,
        "ranking_score": job.ranking_score,
        "ranking_reasons": job.ranking_reasons,
        "posted_at": job.posted_at,
        "source_updated_at": job.source_updated_at,
        "first_seen_at": job.first_seen_at,
        "last_seen_at": job.last_seen_at,
        "closed_at": job.closed_at,
        "is_saved": saved_job_id is not None,
        "saved_job_id": saved_job_id,
        "has_application": application_id is not None,
        "application_id": application_id,
        "application_status": application_status,
    }


def get_job_with_user_state(db: Session, job_id: int, user_id: int | None) -> tuple | None:
    saved_join = and_(SavedJob.job_posting_id == JobPosting.id, SavedJob.user_id == user_id)
    application_join = and_(Application.job_posting_id == JobPosting.id, Application.user_id == user_id)
    return db.execute(
        select(JobPosting, Source, SavedJob.id, Application.id, ApplicationStatus)
        .join(Source, Source.id == JobPosting.source_id)
        .outerjoin(SavedJob, saved_join)
        .outerjoin(Application, application_join)
        .outerjoin(ApplicationStatus, ApplicationStatus.id == Application.status_id)
        .where(JobPosting.id == job_id)
    ).one_or_none()
