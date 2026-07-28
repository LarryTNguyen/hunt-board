from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, Protocol

import httpx

from hunt_board.ingestion.sanitizer import html_to_text

if TYPE_CHECKING:
    from hunt_board.ingestion.sources import SourceConfig


class AdapterError(RuntimeError):
    pass


def parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        timestamp = value / 1000 if value > 10_000_000_000 else value
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


COUNTRY_NAMES = {
    "US": "United States",
    "CA": "Canada",
    "GB": "United Kingdom",
    "AU": "Australia",
    "DE": "Germany",
    "FR": "France",
    "IE": "Ireland",
    "IN": "India",
    "NL": "Netherlands",
    "NZ": "New Zealand",
    "SG": "Singapore",
}
COUNTRY_ALIASES = {
    "us": "US",
    "usa": "US",
    "u.s.": "US",
    "u.s.a.": "US",
    "united states": "US",
    "united states of america": "US",
    "ca": "CA",
    "canada": "CA",
    "gb": "GB",
    "uk": "GB",
    "u.k.": "GB",
    "united kingdom": "GB",
    "australia": "AU",
    "germany": "DE",
    "france": "FR",
    "ireland": "IE",
    "india": "IN",
    "netherlands": "NL",
    "new zealand": "NZ",
    "singapore": "SG",
}
US_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA",
    "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT",
    "VA", "WA", "WV", "WI", "WY", "DC",
}
US_STATE_NAMES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut", "delaware",
    "florida", "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas", "kentucky",
    "louisiana", "maine", "maryland", "massachusetts", "michigan", "minnesota", "mississippi",
    "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey", "new mexico",
    "new york", "north carolina", "north dakota", "ohio", "oklahoma", "oregon", "pennsylvania",
    "rhode island", "south carolina", "south dakota", "tennessee", "texas", "utah", "vermont",
    "virginia", "washington", "west virginia", "wisconsin", "wyoming", "district of columbia",
}
US_LOCATION_HINTS = {"san francisco bay area", "los angeles area", "washington, dc"}


def normalize_country(value: Any, *fallback_values: Any) -> tuple[str | None, str | None]:
    for candidate in (value, *fallback_values):
        if candidate in (None, ""):
            continue
        text = re.sub(r"\s+", " ", str(candidate)).strip()
        lowered = text.casefold()
        if len(text) == 2 and text.isalpha():
            code = text.upper()
            return code, COUNTRY_NAMES.get(code, code)
        direct = COUNTRY_ALIASES.get(lowered)
        if direct:
            return direct, COUNTRY_NAMES[direct]
        for alias, code in sorted(COUNTRY_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
            if len(alias) > 2 and re.search(rf"\b{re.escape(alias)}\b", lowered):
                return code, COUNTRY_NAMES[code]
        if any(re.search(rf"\b{re.escape(state)}\b", lowered) for state in US_STATE_NAMES) or any(
            hint in lowered for hint in US_LOCATION_HINTS
        ):
            return "US", COUNTRY_NAMES["US"]
        state_match = re.search(r",\s*([A-Z]{2})(?:\s+\d{5}(?:-\d{4})?)?\s*$", text)
        if state_match and state_match.group(1) in US_STATE_CODES:
            return "US", COUNTRY_NAMES["US"]
    return None, None


def decimal_or_none(value: Any, *, divisor: int = 1) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        parsed = Decimal(str(value)) / divisor
        return parsed if parsed > 0 else None
    except (InvalidOperation, ValueError, TypeError, ZeroDivisionError):
        return None


def normalize_salary_interval(value: Any) -> str | None:
    if value in (None, ""):
        return None
    normalized = re.sub(r"[\s_-]+", " ", str(value)).strip().casefold()
    aliases = {
        "1 year": "year",
        "annual": "year",
        "annually": "year",
        "yearly": "year",
        "per year salary": "year",
        "per year": "year",
        "1 month": "month",
        "monthly": "month",
        "per month salary": "month",
        "per month": "month",
        "1 week": "week",
        "weekly": "week",
        "per week salary": "week",
        "per week": "week",
        "1 day": "day",
        "daily": "day",
        "per day salary": "day",
        "per day": "day",
        "1 hour": "hour",
        "hourly": "hour",
        "per hour salary": "hour",
        "per hour": "hour",
    }
    return aliases.get(normalized, normalized if normalized in {"year", "month", "week", "day", "hour"} else None)


def salary_range(
    minimum: Any,
    maximum: Any,
    currency: Any = None,
    interval: Any = None,
    *,
    divisor: int = 1,
) -> tuple[Decimal | None, Decimal | None, str | None, str | None]:
    parsed_min = decimal_or_none(minimum, divisor=divisor)
    parsed_max = decimal_or_none(maximum, divisor=divisor)
    parsed_currency = str(currency).strip().upper()[:3] if currency not in (None, "") else None
    return parsed_min, parsed_max, parsed_currency, normalize_salary_interval(interval)


@dataclass(frozen=True)
class NormalizedJob:
    source_slug: str
    company_name: str
    external_job_id: str
    title: str
    location: str | None
    department: str | None
    employment_type: str | None
    workplace_type: str | None
    apply_url: str | None
    description_html: str | None
    description_text: str | None
    raw_json: dict[str, Any]
    location_country_code: str | None = None
    location_country: str | None = None
    salary_min: Decimal | None = None
    salary_max: Decimal | None = None
    salary_currency: str | None = None
    salary_interval: str | None = None
    posting_url: str | None = None
    posted_at: datetime | None = None
    updated_at: datetime | None = None
    locations: list[dict[str, Any]] = field(default_factory=list)


class ATSAdapter(Protocol):
    async def fetch_jobs(self, source: SourceConfig) -> list[NormalizedJob]:
        ...


class HttpATSAdapter:
    TRANSIENT_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}

    def __init__(
        self,
        client: httpx.AsyncClient,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.5,
    ) -> None:
        self.client = client
        self.max_retries = max(0, max_retries)
        self.retry_backoff_seconds = max(0, retry_backoff_seconds)

    async def get_json(self, url: str) -> Any:
        for attempt in range(self.max_retries + 1):
            error: httpx.HTTPError
            try:
                response = await self.client.get(url)
                response.raise_for_status()
                return response.json()
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                error = exc
                should_retry = attempt < self.max_retries
            except httpx.HTTPStatusError as exc:
                error = exc
                should_retry = (
                    exc.response.status_code in self.TRANSIENT_STATUS_CODES
                    and attempt < self.max_retries
                )
            except httpx.HTTPError as exc:
                error = exc
                should_retry = False

            if not should_retry:
                raise AdapterError(f"ATS request failed after {attempt + 1} attempt(s): {error}") from error
            await asyncio.sleep(self.retry_backoff_seconds * (2**attempt))

        raise AssertionError("unreachable")
