from __future__ import annotations

from typing import TYPE_CHECKING, Any

from hunt_board.ingestion.adapters.base import (
    HttpATSAdapter,
    NormalizedJob,
    html_to_text,
    normalize_country,
    parse_datetime,
    salary_range,
)
from hunt_board.ingestion.adapters.base import AdapterError
from hunt_board.ingestion.sanitizer import sanitized_description

if TYPE_CHECKING:
    from hunt_board.ingestion.sources import SourceConfig


class LeverAdapter(HttpATSAdapter):
    async def fetch_jobs(self, source: SourceConfig) -> list[NormalizedJob]:
        site = source.config.get("site")
        if not site:
            raise AdapterError(f"Lever source '{source.slug}' requires config.site")
        jobs = await self.get_json(f"https://api.lever.co/v0/postings/{site}?mode=json")
        return [self.normalize(source, job) for job in jobs]

    def normalize(self, source: SourceConfig, job: dict[str, Any]) -> NormalizedJob:
        categories: dict[str, Any] = job.get("categories") or {}
        description_html = job.get("descriptionHtml")
        description_html, description_text = sanitized_description(
            description_html, html_to_text(job.get("descriptionPlain"))
        )
        country_code, country_name = normalize_country(job.get("country"), categories.get("location"))
        salary = job.get("salaryRange") or {}
        salary_min, salary_max, salary_currency, salary_interval = salary_range(
            salary.get("min"), salary.get("max"), salary.get("currency"), salary.get("interval")
        )
        return NormalizedJob(
            source_slug=source.slug,
            company_name=source.company_name,
            external_job_id=str(job["id"]),
            title=job.get("text") or "Untitled job",
            location=categories.get("location"),
            location_country_code=country_code,
            location_country=country_name,
            department=categories.get("team"),
            employment_type=categories.get("commitment"),
            workplace_type=categories.get("workplaceType"),
            posting_url=job.get("hostedUrl"),
            apply_url=job.get("applyUrl") or job.get("hostedUrl"),
            description_html=description_html,
            description_text=description_text,
            raw_json=job,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=salary_currency,
            salary_interval=salary_interval,
            posted_at=parse_datetime(job.get("createdAt")),
            updated_at=parse_datetime(job.get("updatedAt")),
        )
