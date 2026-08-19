from __future__ import annotations

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, undefer

from hunt_board.db.models import Application, ApplicationStatus, DiscardedJob, JobPosting, SavedJob, Source, UserJobState


def source_summary(source: Source | None) -> dict | None:
    if source is None:
        return None
    return {
        "id": source.id,
        "slug": source.slug,
        "name": source.name,
        "ats": source.ats,
        "company_name": source.company_name,
        "company_logo_url": source.company_logo_url,
    }


def job_summary(job: JobPosting, source: Source | None = None) -> dict:
    return {
        "id": job.id,
        "source_slug": job.source_slug,
        "title": job.title,
        "company_name": job.company_name,
        "location": job.location,
        "location_country_code": job.location_country_code,
        "location_country": job.location_country,
        "locations": job.locations_json or [],
        "salary_min": job.salary_min,
        "salary_max": job.salary_max,
        "salary_currency": job.salary_currency,
        "salary_interval": job.salary_interval,
        "company_logo_url": source.company_logo_url if source else None,
        "apply_url": job.apply_url,
        "ranking_score": job.ranking_score,
        "active": job.active,
        "duplicate_status": job.duplicate_status,
        "duplicate_of_job_id": job.duplicate_of_job_id,
        "reposted_at": job.reposted_at,
        "job_family_slug": job.job_family_slug,
        "sponsorship_status": job.sponsorship_status,
        "remote_scope": job.remote_scope,
    }


def job_read_payload(
    job: JobPosting,
    source: Source | None,
    saved_job_id: int | None,
    discarded_job_id: int | None,
    discarded_at: datetime | None,
    application_id: int | None,
    application_status: ApplicationStatus | None,
    seen_at: datetime | None,
    *,
    include_descriptions: bool = True,
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
        "location_country_code": job.location_country_code,
        "location_country": job.location_country,
        "locations": job.locations_json or [],
        "department": job.department,
        "employment_type": job.employment_type,
        "workplace_type": job.workplace_type,
        "salary_min": job.salary_min,
        "salary_max": job.salary_max,
        "salary_currency": job.salary_currency,
        "salary_interval": job.salary_interval,
        "company_logo_url": source.company_logo_url if source else None,
        "posting_url": job.posting_url,
        "apply_url": job.apply_url,
        "description_html": job.description_html if include_descriptions else None,
        "description_text": job.description_text if include_descriptions else None,
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
        "is_discarded": discarded_job_id is not None,
        "discarded_job_id": discarded_job_id,
        "discarded_at": discarded_at,
        "has_application": application_id is not None,
        "application_id": application_id,
        "application_status": application_status,
        "is_seen": seen_at is not None,
        "seen_at": seen_at,
        "job_family_slug": job.job_family_slug,
        "classification_confidence": job.classification_confidence,
        "classification_method": job.classification_method,
        "classification_reason": job.classification_reason,
        "classification_overridden_at": job.classification_overridden_at,
        "sponsorship_status": job.sponsorship_status,
        "remote_scope": job.remote_scope,
    }


def get_job_with_user_state(db: Session, job_id: int, user_id: int | None) -> tuple | None:
    saved_join = and_(SavedJob.job_posting_id == JobPosting.id, SavedJob.user_id == user_id)
    discarded_join = and_(DiscardedJob.job_posting_id == JobPosting.id, DiscardedJob.user_id == user_id)
    combined_state_join = and_(UserJobState.job_posting_id == JobPosting.id, UserJobState.user_id == user_id)
    latest_application_id = (
        select(func.max(Application.id))
        .where(
            Application.job_posting_id == JobPosting.id,
            Application.user_id == user_id,
            Application.deleted_at.is_(None),
        )
        .correlate(JobPosting)
        .scalar_subquery()
    )
    application_join = Application.id == latest_application_id
    return db.execute(
        select(
            JobPosting,
            Source,
            SavedJob.id,
            DiscardedJob.id,
            DiscardedJob.created_at,
            Application.id,
            ApplicationStatus,
            UserJobState.seen_at,
        )
        .join(Source, Source.id == JobPosting.source_id)
        .outerjoin(SavedJob, saved_join)
        .outerjoin(DiscardedJob, discarded_join)
        .outerjoin(UserJobState, combined_state_join)
        .outerjoin(Application, application_join)
        .outerjoin(ApplicationStatus, ApplicationStatus.id == Application.status_id)
        .where(JobPosting.id == job_id)
        .options(
            undefer(JobPosting.description_html),
            undefer(JobPosting.description_text),
        )
    ).one_or_none()
