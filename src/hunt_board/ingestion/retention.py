from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from hunt_board.db.models import JobPosting, JobVersion

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RawPayloadPurgeResult:
    dry_run: bool
    postings_considered: int
    postings_purged: int
    versions_considered: int
    versions_purged: int


def purge_expired_raw_payloads(
    db: Session,
    *,
    dry_run: bool = False,
    now: datetime | None = None,
) -> RawPayloadPurgeResult:
    cutoff = now or datetime.now(timezone.utc)
    posting_filter = (
        JobPosting.raw_json_expires_at.is_not(None),
        JobPosting.raw_json_expires_at <= cutoff,
    )
    version_filter = (
        JobVersion.raw_json_expires_at.is_not(None),
        JobVersion.raw_json_expires_at <= cutoff,
    )
    postings_considered = int(
        db.scalar(select(func.count(JobPosting.id)).where(*posting_filter)) or 0
    )
    versions_considered = int(
        db.scalar(select(func.count(JobVersion.id)).where(*version_filter)) or 0
    )
    if not dry_run:
        db.execute(
            update(JobPosting)
            .where(*posting_filter)
            .values(raw_json={}, raw_json_expires_at=None)
            .execution_options(synchronize_session=False)
        )
        db.execute(
            update(JobVersion)
            .where(*version_filter)
            .values(raw_json={}, raw_json_expires_at=None)
            .execution_options(synchronize_session=False)
        )
        db.commit()
        db.expire_all()
    result = RawPayloadPurgeResult(
        dry_run=dry_run,
        postings_considered=postings_considered,
        postings_purged=0 if dry_run else postings_considered,
        versions_considered=versions_considered,
        versions_purged=0 if dry_run else versions_considered,
    )
    logger.info(
        "Expired raw payload cleanup finished: postings=%s versions=%s dry_run=%s",
        result.postings_purged,
        result.versions_purged,
        dry_run,
    )
    return result
