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


class GreenhouseAdapter(HttpATSAdapter):
    async def fetch_jobs(self, source: SourceConfig) -> list[NormalizedJob]:
        token = source.config.get("board_token")
        if not token:
            raise AdapterError(f"Greenhouse source '{source.slug}' requires config.board_token")
        payload = await self.get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true")
        jobs = payload.get("jobs", []) if isinstance(payload, dict) else payload
        return [self.normalize(source, job) for job in jobs]

    def normalize(self, source: SourceConfig, job: dict[str, Any]) -> NormalizedJob:
        location = job.get("location") or {}
        departments = job.get("departments") or []
        offices = job.get("offices") or []
        description_html = job.get("content")
        description_html, description_text = sanitized_description(description_html)
        location_name = location.get("name") or ", ".join(o.get("name", "") for o in offices if o.get("name")) or None
        office_locations = [office.get("location") for office in offices if office.get("location")]
        country_code, country_name = normalize_country(None, *office_locations, location_name)
        pay_ranges = job.get("pay_input_ranges") or []
        salary = next((item for item in pay_ranges if isinstance(item, dict)), {})
        salary_min, salary_max, salary_currency, salary_interval = salary_range(
            salary.get("min_cents"), salary.get("max_cents"), salary.get("currency_type"), divisor=100
        )
        return NormalizedJob(
            source_slug=source.slug,
            company_name=source.company_name,
            external_job_id=str(job["id"]),
            title=job.get("title") or "Untitled job",
            location=location_name,
            location_country_code=country_code,
            location_country=country_name,
            department=", ".join(d.get("name", "") for d in departments if d.get("name")) or None,
            employment_type=job.get("metadata", {}).get("employment_type") if isinstance(job.get("metadata"), dict) else None,
            workplace_type=job.get("metadata", {}).get("workplace_type") if isinstance(job.get("metadata"), dict) else None,
            posting_url=job.get("absolute_url"),
            apply_url=job.get("absolute_url"),
            description_html=description_html,
            description_text=description_text,
            raw_json=job,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=salary_currency,
            salary_interval=salary_interval,
            posted_at=parse_datetime(job.get("created_at")),
            updated_at=parse_datetime(job.get("updated_at")),
        )
