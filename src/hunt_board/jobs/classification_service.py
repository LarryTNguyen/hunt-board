from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session, undefer

from hunt_board.db.models import JobPosting, Source
from hunt_board.jobs.classification import apply_classification, classify_job


@dataclass(frozen=True)
class ReclassificationResult:
    considered: int
    updated: int
    overrides_preserved: int


def reclassify_jobs(db: Session, *, include_overrides: bool = False) -> ReclassificationResult:
    jobs = list(
        db.scalars(
            select(JobPosting)
            .options(undefer(JobPosting.description_text))
            .order_by(JobPosting.id)
        ).all()
    )
    updated = 0
    preserved = 0
    for job in jobs:
        if job.classification_overridden_at is not None and not include_overrides:
            preserved += 1
            continue
        if include_overrides:
            job.classification_overridden_at = None
            job.classification_overridden_by_user_id = None
            job.classification_override_reason = None
        result = classify_job(department=job.department, title=job.title, description=job.description_text)
        before = (job.job_family_slug, job.classification_method, job.classification_reason)
        apply_classification(job, result)
        updated += int(before != (job.job_family_slug, job.classification_method, job.classification_reason))
    db.commit()
    return ReclassificationResult(len(jobs), updated, preserved)


def coverage_report(db: Session) -> dict:
    def rows(*columns):
        result = db.execute(
            select(*columns, func.count(JobPosting.id).label("count"))
            .select_from(JobPosting)
            .join(Source, Source.id == JobPosting.source_id)
            .where(JobPosting.active.is_(True))
            .group_by(*columns)
            .order_by(func.count(JobPosting.id).desc())
        ).all()
        return [dict(zip([column.key for column in columns], row[:-1]), count=int(row[-1])) for row in result]

    total = int(db.scalar(select(func.count(JobPosting.id)).where(JobPosting.active.is_(True))) or 0)
    return {
        "active_jobs": total,
        "by_family": rows(JobPosting.job_family_slug),
        "by_ats": rows(Source.ats),
        "by_company": rows(JobPosting.company_name),
        "other_rate": (
            round(
                100
                * int(
                    db.scalar(
                        select(func.count(JobPosting.id)).where(
                            JobPosting.active.is_(True), JobPosting.job_family_slug == "other"
                        )
                    )
                    or 0
                )
                / total,
                2,
            )
            if total
            else 0.0
        ),
    }
