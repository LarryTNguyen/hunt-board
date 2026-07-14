from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Protocol

import httpx

from hunt_board.ingestion.sources import SourceConfig


class AdapterError(RuntimeError):
    pass


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.parts.append(text)


def html_to_text(html: str | None) -> str | None:
    if not html:
        return None
    parser = _TextExtractor()
    parser.feed(html)
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip() or None


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
    posting_url: str | None = None
    posted_at: datetime | None = None
    updated_at: datetime | None = None


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
