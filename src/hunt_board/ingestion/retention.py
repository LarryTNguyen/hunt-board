from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging

from sqlalchemy import select
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
    postings = list(
        db.scalars(
            select(JobPosting).where(
                JobPosting.raw_json_expires_at.is_not(None),
                JobPosting.raw_json_expires_at <= cutoff,
            )
        ).all()
    )
    versions = list(
        db.scalars(
            select(JobVersion).where(
                JobVersion.raw_json_expires_at.is_not(None),
                JobVersion.raw_json_expires_at <= cutoff,
            )
        ).all()
    )
    if not dry_run:
        for record in (*postings, *versions):
            record.raw_json = {}
            record.raw_json_expires_at = None
        db.commit()
    result = RawPayloadPurgeResult(
        dry_run=dry_run,
        postings_considered=len(postings),
        postings_purged=0 if dry_run else len(postings),
        versions_considered=len(versions),
        versions_purged=0 if dry_run else len(versions),
    )
    logger.info(
        "Expired raw payload cleanup finished: postings=%s versions=%s dry_run=%s",
        result.postings_purged,
        result.versions_purged,
        dry_run,
    )
    return result
