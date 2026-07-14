from __future__ import annotations

from typing import Any

from hunt_board.ingestion.adapters.base import HttpATSAdapter, NormalizedJob, html_to_text, parse_datetime
from hunt_board.ingestion.sources import SourceConfig


class AshbyAdapter(HttpATSAdapter):
    async def fetch_jobs(self, source: SourceConfig) -> list[NormalizedJob]:
        organization = source.config.get("organization")
        if not organization:
            raise ValueError(f"Ashby source {source.slug} requires config.organization")
        payload = await self.get_json(f"https://api.ashbyhq.com/posting-api/job-board/{organization}")
        jobs = payload.get("jobs", []) if isinstance(payload, dict) else payload
        return [self.normalize(source, job) for job in jobs]

    def normalize(self, source: SourceConfig, job: dict[str, Any]) -> NormalizedJob:
        description_html = job.get("descriptionHtml")
        location_value = job.get("location")
        department_value = job.get("department")
        location = job.get("locationName") or (
            location_value.get("name") if isinstance(location_value, dict) else location_value
        )
        department = job.get("departmentName") or (
            department_value.get("name") if isinstance(department_value, dict) else department_value
        )
        return NormalizedJob(
            source_slug=source.slug,
            company_name=source.company_name,
            external_job_id=str(job["id"]),
            title=job.get("title") or "Untitled job",
            location=location,
            department=department,
            employment_type=job.get("employmentType"),
            workplace_type=job.get("workplaceType"),
            posting_url=job.get("jobUrl"),
            apply_url=job.get("applyUrl") or job.get("jobUrl"),
            description_html=description_html,
            description_text=job.get("descriptionPlain") or html_to_text(description_html),
            raw_json=job,
            posted_at=parse_datetime(job.get("publishedAt")),
            updated_at=parse_datetime(job.get("updatedAt")),
        )
