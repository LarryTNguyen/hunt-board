from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from hunt_board.api.schemas import JobPostingRead
from hunt_board.db.models import JobPosting
from hunt_board.db.session import get_db

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobPostingRead])
def list_jobs(
    active: bool | None = Query(default=True),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[JobPosting]:
    statement = select(JobPosting).order_by(JobPosting.ranking_score.desc(), JobPosting.last_seen_at.desc()).limit(limit)
    if active is not None:
        statement = statement.where(JobPosting.active.is_(active))
    return list(db.scalars(statement).all())


@router.get("/{job_id}", response_model=JobPostingRead)
def get_job(job_id: int, db: Session = Depends(get_db)) -> JobPosting:
    job = db.get(JobPosting, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
