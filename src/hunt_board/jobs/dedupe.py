from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from hunt_board.db.models import JobPosting, Source
from hunt_board.ingestion.adapters.base import NormalizedJob


DedupeAction = Literal["create", "upsert", "possible_duplicate"]


@dataclass(frozen=True)
class DedupeDecision:
    action: DedupeAction
    existing_job: JobPosting | None = None
    reason: str | None = None
    reactivated: bool = False


TRACKING_PARAMS = {"gh_src", "lever-origin", "source", "utm_campaign", "utm_content", "utm_medium", "utm_source", "utm_term"}


def normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    return re.sub(r"\s+", " ", normalized) or None


def canonicalize_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value.strip())
    query = urlencode(
        [(key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True) if key.lower() not in TRACKING_PARAMS]
    )
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, query, ""))


def decide_dedupe(
    db: Session,
    source: Source | None,
    job: NormalizedJob,
    *,
    active_by_external_id: dict[str, JobPosting] | None = None,
) -> DedupeDecision:
    source_identity = (
        JobPosting.source_id == source.id
        if source is not None and source.id is not None
        else JobPosting.source_slug == job.source_slug
    )
    same_external = (active_by_external_id or {}).get(job.external_job_id)
    if same_external is None:
        same_external = db.scalar(
            select(JobPosting).where(
                source_identity,
                JobPosting.external_job_id == job.external_job_id,
            )
        )
    if same_external:
        return DedupeDecision("upsert", same_external, "same source and external_job_id", not same_external.active)

    canonical_url = canonicalize_url(job.apply_url)
    if canonical_url:
        same_url = db.scalar(select(JobPosting).where(JobPosting.canonical_apply_url == canonical_url))
        if same_url:
            return DedupeDecision("upsert", same_url, "same canonical apply_url", not same_url.active)

    normalized_title = normalize_text(job.title)
    normalized_location = normalize_text(job.location)
    possible = db.scalar(
        select(JobPosting).where(
            JobPosting.company_name == job.company_name,
            JobPosting.normalized_title == normalized_title,
            JobPosting.normalized_location == normalized_location,
        )
    )
    if possible:
        return DedupeDecision(
            "possible_duplicate",
            possible,
            "same company, normalized title, and normalized location",
            not possible.active,
        )

    return DedupeDecision("create")
