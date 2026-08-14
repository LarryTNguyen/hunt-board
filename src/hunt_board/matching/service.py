from __future__ import annotations

import logging
from datetime import datetime, timezone
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from hunt_board.db.models import JobMatch, JobPosting, Source, User, UserPreference
from hunt_board.ingestion.adapters.base import NormalizedJob
from hunt_board.matching.ranking import UserPreferences, rank_job


RESCORE_BATCH_SIZE = 250
logger = logging.getLogger("hunt_board")


def preferences_from_row(preference: UserPreference) -> UserPreferences:
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
        selected_job_families=preference.selected_job_families,
        related_job_families=preference.related_job_families,
        desired_titles=preference.desired_titles,
        preferred_countries=preference.preferred_countries,
        excluded_countries=preference.excluded_countries,
        workplace_preferences=preference.workplace_preferences,
        employment_types=preference.employment_types,
        sponsorship_required=preference.sponsorship_required,
        minimum_salary=preference.minimum_salary,
        excluded_companies=preference.excluded_companies,
    )


def ensure_user_preference(db: Session, user: User) -> UserPreference:
    preference = db.scalar(select(UserPreference).where(UserPreference.user_id == user.id))
    if preference is not None:
        return preference
    defaults = UserPreferences.model_validate(user.preferences_json) if user.preferences_json else UserPreferences(
        include_keywords=[],
        exclude_keywords=[],
        role_groups=[],
        preferred_levels=[],
        preferred_locations=[],
        home_location="",
        radius_miles=0,
        country="",
        remote_allowed=True,
        minimum_score_threshold=0,
    )
    preference = UserPreference(user_id=user.id, **defaults.model_dump())
    db.add(preference)
    db.flush()
    return preference


def normalized_job_from_posting(job: JobPosting) -> NormalizedJob:
    return NormalizedJob(
        source_slug=job.source_slug,
        company_name=job.company_name,
        external_job_id=job.external_job_id or str(job.id),
        title=job.title,
        location=job.location,
        department=job.department,
        employment_type=job.employment_type,
        workplace_type=job.workplace_type,
        posting_url=job.posting_url,
        apply_url=job.apply_url,
        description_html=job.description_html,
        description_text=job.description_text,
        raw_json=job.raw_json,
        posted_at=job.posted_at,
        updated_at=job.source_updated_at,
    )


def rescore_jobs(db: Session, user: User, preference: UserPreference) -> dict:
    started_at = datetime.now(timezone.utc)
    timer = perf_counter()
    prefs = preferences_from_row(preference)
    visible = 0
    total_jobs = 0
    last_job_id = 0
    batch_number = 0
    try:
        while True:
            rows = db.execute(
                select(
                    JobPosting.id,
                    JobPosting.title,
                    JobPosting.location,
                    JobPosting.workplace_type,
                    JobPosting.posted_at,
                    JobPosting.active,
                    JobPosting.duplicate_status,
                    Source.priority,
                )
                .join(Source, Source.id == JobPosting.source_id)
                .where(JobPosting.id > last_job_id)
                .order_by(JobPosting.id)
                .limit(RESCORE_BATCH_SIZE)
            ).all()
            if not rows:
                break

            batch_number += 1
            job_updates = []
            match_updates = []
            match_inserts = []
            job_ids = [row.id for row in rows]
            existing_matches = {
                job_id: match_id
                for match_id, job_id in db.execute(
                    select(JobMatch.id, JobMatch.job_posting_id).where(
                        JobMatch.user_id == user.id,
                        JobMatch.job_posting_id.in_(job_ids),
                    )
                ).all()
            }

            for row in rows:
                ranking = rank_job(
                    NormalizedJob(
                        source_slug="",
                        company_name="",
                        external_job_id=str(row.id),
                        title=row.title,
                        location=row.location,
                        department=None,
                        employment_type=None,
                        workplace_type=row.workplace_type,
                        apply_url=None,
                        description_html=None,
                        description_text=None,
                        raw_json={},
                        posted_at=row.posted_at,
                    ),
                    prefs,
                    row.priority,
                )
                job_updates.append({
                    "id": row.id,
                    "ranking_score": ranking.score,
                    "ranking_reasons": ranking.reasons,
                })
                match_values = {
                    "score": ranking.score,
                    "matched": ranking.matched,
                    "reasons": ranking.reasons,
                }
                match_id = existing_matches.get(row.id)
                if match_id is None:
                    match_inserts.append({
                        "user_id": user.id,
                        "job_posting_id": row.id,
                        **match_values,
                    })
                else:
                    match_updates.append({"id": match_id, **match_values})
                if (
                    row.active
                    and row.duplicate_status != "duplicate"
                    and ranking.matched
                    and ranking.score >= prefs.minimum_score_threshold
                ):
                    visible += 1

            db.bulk_update_mappings(JobPosting, job_updates)
            if match_updates:
                db.bulk_update_mappings(JobMatch, match_updates)
            if match_inserts:
                db.bulk_insert_mappings(JobMatch, match_inserts)
            db.commit()
            total_jobs += len(rows)
            last_job_id = rows[-1].id
            logger.info(
                "preference.rescore.batch_completed",
                extra={
                    "event_name": "preference.rescore.batch_completed",
                    "event_data": {
                        "user_id": user.id,
                        "batch_number": batch_number,
                        "batch_size": len(rows),
                        "total_jobs_processed": total_jobs,
                        "last_job_id": last_job_id,
                        "duration_ms": round((perf_counter() - timer) * 1000),
                    },
                },
            )
    except Exception as exc:
        logger.error(
            "preference.rescore.batch_failed",
            extra={
                "event_name": "preference.rescore.batch_failed",
                "event_data": {
                    "user_id": user.id,
                    "batch_number": batch_number,
                    "total_jobs_processed": total_jobs,
                    "last_job_id": last_job_id,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            },
        )
        raise
    finished_at = datetime.now(timezone.utc)
    return {
        "total_jobs_considered": total_jobs,
        "total_jobs_rescored": total_jobs,
        "total_visible_jobs": visible,
        "total_hidden_or_low_ranked_jobs": total_jobs - visible,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": round((perf_counter() - timer) * 1000),
    }
