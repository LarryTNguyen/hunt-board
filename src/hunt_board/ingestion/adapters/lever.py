from __future__ import annotations

from typing import Any

from hunt_board.ingestion.adapters.base import HttpATSAdapter, NormalizedJob, html_to_text, parse_datetime
from hunt_board.ingestion.sources import SourceConfig


class LeverAdapter(HttpATSAdapter):
    async def fetch_jobs(self, source: SourceConfig) -> list[NormalizedJob]:
        site = source.config.get("site")
        if not site:
            raise ValueError(f"Lever source {source.slug} requires config.site")
        jobs = await self.get_json(f"https://api.lever.co/v0/postings/{site}?mode=json")
        return [self.normalize(source, job) for job in jobs]

    def normalize(self, source: SourceConfig, job: dict[str, Any]) -> NormalizedJob:
        categories: dict[str, Any] = job.get("categories") or {}
        description_html = job.get("descriptionHtml")
        return NormalizedJob(
            source_slug=source.slug,
            company_name=source.company_name,
            external_job_id=str(job["id"]),
            title=job.get("text") or "Untitled job",
            location=categories.get("location"),
            department=categories.get("team"),
            employment_type=categories.get("commitment"),
            workplace_type=categories.get("workplaceType"),
            posting_url=job.get("hostedUrl"),
            apply_url=job.get("applyUrl") or job.get("hostedUrl"),
            description_html=description_html,
            description_text=job.get("descriptionPlain") or html_to_text(description_html),
            raw_json=job,
            posted_at=parse_datetime(job.get("createdAt")),
            updated_at=parse_datetime(job.get("updatedAt")),
        )
