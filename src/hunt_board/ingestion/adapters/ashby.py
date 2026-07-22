from __future__ import annotations

from typing import Any

from hunt_board.ingestion.adapters.base import (
    HttpATSAdapter,
    NormalizedJob,
    html_to_text,
    normalize_country,
    parse_datetime,
    salary_range,
)
from hunt_board.ingestion.sources import SourceConfig


class AshbyAdapter(HttpATSAdapter):
    async def fetch_jobs(self, source: SourceConfig) -> list[NormalizedJob]:
        organization = source.config.get("organization")
        if not organization:
            raise ValueError(f"Ashby source {source.slug} requires config.organization")
        payload = await self.get_json(
            f"https://api.ashbyhq.com/posting-api/job-board/{organization}?includeCompensation=true"
        )
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
        address = job.get("address") or {}
        postal_address = address.get("postalAddress") or {} if isinstance(address, dict) else {}
        secondary_locations = job.get("secondaryLocations") or []
        secondary_countries = [
            (item.get("address") or {}).get("addressCountry")
            for item in secondary_locations
            if isinstance(item, dict) and isinstance(item.get("address"), dict)
        ]
        country_code, country_name = normalize_country(
            postal_address.get("addressCountry"), *secondary_countries, location
        )
        compensation = job.get("compensation") or {}
        components = compensation.get("summaryComponents") or [] if isinstance(compensation, dict) else []
        salary_component = next(
            (
                component
                for component in components
                if isinstance(component, dict) and str(component.get("compensationType", "")).casefold() == "salary"
            ),
            {},
        )
        salary_min, salary_max, salary_currency, salary_interval = salary_range(
            salary_component.get("minValue"),
            salary_component.get("maxValue"),
            salary_component.get("currencyCode"),
            salary_component.get("interval"),
        )
        return NormalizedJob(
            source_slug=source.slug,
            company_name=source.company_name,
            external_job_id=str(job["id"]),
            title=job.get("title") or "Untitled job",
            location=location,
            location_country_code=country_code,
            location_country=country_name,
            department=department,
            employment_type=job.get("employmentType"),
            workplace_type=job.get("workplaceType"),
            posting_url=job.get("jobUrl"),
            apply_url=job.get("applyUrl") or job.get("jobUrl"),
            description_html=description_html,
            description_text=html_to_text(job.get("descriptionPlain")) or html_to_text(description_html),
            raw_json=job,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=salary_currency,
            salary_interval=salary_interval,
            posted_at=parse_datetime(job.get("publishedAt")),
            updated_at=parse_datetime(job.get("updatedAt")),
        )
