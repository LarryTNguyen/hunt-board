from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from hunt_board.auth.dependencies import require_user
from hunt_board.dashboard.schemas import DailyDashboardRead
from hunt_board.db.models import (
    Application,
    ApplicationStatus,
    DiscardedJob,
    DuplicateReview,
    JobPosting,
    Notification,
    SavedJob,
    SavedSearch,
    Source,
    User,
    UserPreference,
)
from hunt_board.db.session import get_db
from hunt_board.jobs.query import (
    JobQueryFilters,
    apply_job_filters,
    job_row_statement,
)
from hunt_board.jobs.service import job_read_payload, job_summary
from hunt_board.searches.service import match_statement, saved_search_payload


router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _count(db: Session, statement) -> int:
    return int(db.scalar(statement) or 0)


@router.get("/daily", response_model=DailyDashboardRead)
def daily_dashboard(
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    now = datetime.now(timezone.utc)
    day_cutoff = now - timedelta(hours=24)
    week_cutoff = now - timedelta(days=7)
    follow_up_cutoff = now - timedelta(days=7)

    searches = list(
        db.scalars(
            select(SavedSearch)
            .where(SavedSearch.user_id == user.id, SavedSearch.is_active.is_(True))
            .order_by(
                SavedSearch.is_default.desc(),
                SavedSearch.updated_at.desc(),
                SavedSearch.id.desc(),
            )
        ).all()
    )
    search_payloads = [
        saved_search_payload(db, item, user.id, preview_limit=3)
        for item in searches
    ]
    saved_search_new_matches = sum(
        item["new_since_review_count"] for item in search_payloads
    )

    candidate_ids: set[int] = set()
    for saved_search in searches:
        statement, _, _ = match_statement(
            db, saved_search, user.id, new_only=True
        )
        if saved_search.last_viewed_at is None:
            id_statement = statement.with_only_columns(JobPosting.id).order_by(None)
        else:
            id_statement = (
                statement.where(
                    JobPosting.first_seen_at > saved_search.last_viewed_at
                )
                .with_only_columns(JobPosting.id)
                .order_by(None)
            )
        candidate_ids.update(db.scalars(id_statement).all())

    if not searches:
        preference = db.scalar(
            select(UserPreference).where(UserPreference.user_id == user.id)
        )
        fallback_filters = JobQueryFilters(
            active=True,
            discarded=False,
            application_state="none",
            include_duplicates=False,
            min_score=preference.minimum_score_threshold if preference else 60,
        )
        fallback, _ = apply_job_filters(
            job_row_statement(user.id), db, fallback_filters
        )
        candidate_ids.update(
            db.scalars(
                fallback.where(JobPosting.first_seen_at >= week_cutoff)
                .with_only_columns(JobPosting.id)
                .order_by(None)
            ).all()
        )

    top_new_matches = []
    if candidate_ids:
        top_rows = db.execute(
            job_row_statement(user.id)
            .where(JobPosting.id.in_(candidate_ids))
            .order_by(
                JobPosting.ranking_score.desc(),
                JobPosting.first_seen_at.desc(),
                JobPosting.id.desc(),
            )
            .limit(10)
        ).all()
        top_new_matches = [job_read_payload(*row) for row in top_rows]

    application_join = and_(
        Application.status_id == ApplicationStatus.id,
        Application.user_id == user.id,
    )
    pipeline_rows = db.execute(
        select(
            ApplicationStatus.slug,
            ApplicationStatus.name,
            ApplicationStatus.sort_order,
            func.count(Application.id),
        )
        .outerjoin(Application, application_join)
        .group_by(
            ApplicationStatus.id,
            ApplicationStatus.slug,
            ApplicationStatus.name,
            ApplicationStatus.sort_order,
        )
        .order_by(ApplicationStatus.sort_order, ApplicationStatus.id)
    ).all()

    follow_up_rows = db.execute(
        select(Application, JobPosting, Source, ApplicationStatus)
        .join(JobPosting, JobPosting.id == Application.job_posting_id)
        .join(Source, Source.id == JobPosting.source_id)
        .join(ApplicationStatus, ApplicationStatus.id == Application.status_id)
        .where(
            Application.user_id == user.id,
            ApplicationStatus.is_terminal.is_(False),
            Application.updated_at <= follow_up_cutoff,
        )
        .order_by(Application.updated_at.asc(), Application.id.asc())
        .limit(10)
    ).all()
    follow_ups = [
        {
            "id": application.id,
            "notes": application.notes,
            "created_at": application.created_at,
            "updated_at": application.updated_at,
            "status": status,
            "job": job_summary(job, source),
        }
        for application, job, source, status in follow_up_rows
    ]

    active_applications = _count(
        db,
        select(func.count(Application.id))
        .join(ApplicationStatus, ApplicationStatus.id == Application.status_id)
        .where(
            Application.user_id == user.id,
            ApplicationStatus.is_terminal.is_(False),
        ),
    )
    terminal_applications = _count(
        db,
        select(func.count(Application.id))
        .join(ApplicationStatus, ApplicationStatus.id == Application.status_id)
        .where(
            Application.user_id == user.id,
            ApplicationStatus.is_terminal.is_(True),
        ),
    )
    totals = {
        "active_jobs": _count(
            db,
            select(func.count(JobPosting.id)).where(JobPosting.active.is_(True)),
        ),
        "jobs_first_seen_last_24_hours": _count(
            db,
            select(func.count(JobPosting.id)).where(
                JobPosting.first_seen_at >= day_cutoff
            ),
        ),
        "jobs_first_seen_last_7_days": _count(
            db,
            select(func.count(JobPosting.id)).where(
                JobPosting.first_seen_at >= week_cutoff
            ),
        ),
        "saved_jobs": _count(
            db,
            select(func.count(SavedJob.id)).where(SavedJob.user_id == user.id),
        ),
        "discarded_jobs": _count(
            db,
            select(func.count(DiscardedJob.id)).where(
                DiscardedJob.user_id == user.id
            ),
        ),
        "active_applications": active_applications,
        "terminal_applications": terminal_applications,
        "unread_notifications": _count(
            db,
            select(func.count(Notification.id)).where(
                Notification.user_id == user.id,
                Notification.read_at.is_(None),
            ),
        ),
        "open_duplicate_reviews": _count(
            db,
            select(func.count(DuplicateReview.id)).where(
                DuplicateReview.status == "open"
            ),
        ),
        "active_saved_searches": len(searches),
        "saved_search_new_matches": saved_search_new_matches,
    }
    return {
        "generated_at": now,
        "totals": totals,
        "saved_searches": search_payloads,
        "top_new_matches": top_new_matches,
        "application_pipeline": [
            {
                "slug": slug,
                "name": name,
                "sort_order": sort_order,
                "count": count,
            }
            for slug, name, sort_order, count in pipeline_rows
        ],
        "follow_up_candidates": follow_ups,
    }
