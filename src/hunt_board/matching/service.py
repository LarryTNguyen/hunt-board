from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from hunt_board.db.models import JobMatch, JobPosting, Source, User, UserPreference
from hunt_board.ingestion.adapters.base import NormalizedJob
from hunt_board.matching.ranking import UserPreferences, rank_job


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
    rows = db.execute(
        select(JobPosting, Source).join(Source, Source.id == JobPosting.source_id).order_by(JobPosting.id)
    ).all()
    visible = 0
    for job, source in rows:
        ranking = rank_job(normalized_job_from_posting(job), prefs, source.priority)
        job.ranking_score = ranking.score
        job.ranking_reasons = ranking.reasons
        match = db.scalar(
            select(JobMatch).where(JobMatch.user_id == user.id, JobMatch.job_posting_id == job.id)
        )
        if match is None:
            match = JobMatch(user_id=user.id, job_posting_id=job.id)
            db.add(match)
        match.score = ranking.score
        match.matched = ranking.matched
        match.reasons = ranking.reasons
        if (
            job.active
            and job.duplicate_status != "duplicate"
            and ranking.matched
            and ranking.score >= prefs.minimum_score_threshold
        ):
            visible += 1
    db.commit()
    finished_at = datetime.now(timezone.utc)
    return {
        "total_jobs_considered": len(rows),
        "total_jobs_rescored": len(rows),
        "total_visible_jobs": visible,
        "total_hidden_or_low_ranked_jobs": len(rows) - visible,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": round((perf_counter() - timer) * 1000),
    }
