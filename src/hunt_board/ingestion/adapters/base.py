from __future__ import annotations

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
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def get_json(self, url: str) -> Any:
        try:
            response = await self.client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AdapterError(f"ATS request failed: {exc}") from exc
        return response.json()
