from __future__ import annotations

import json
from pathlib import Path
from decimal import Decimal

import httpx
import pytest

from hunt_board.ingestion.adapters import AshbyAdapter, GreenhouseAdapter, LeverAdapter
from hunt_board.ingestion.adapters.base import decimal_or_none, html_to_text, normalize_country, normalize_salary_interval
from hunt_board.ingestion.sources import SourceConfig


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_html_to_text_removes_markup_from_html_and_plain_fields() -> None:
    assert html_to_text("<div>Build <strong>Python APIs</strong></div>") == "Build Python APIs"
    assert html_to_text("Plain description text") == "Plain description text"


def test_country_and_salary_helpers_normalize_explicit_values() -> None:
    assert normalize_country("US") == ("US", "United States")
    assert normalize_country(None, "San Francisco, CA") == ("US", "United States")
    assert normalize_country(None, "Toronto, Canada") == ("CA", "Canada")
    assert normalize_country(None, "San Francisco, California") == ("US", "United States")
    assert normalize_country(None, "San Francisco Bay Area or Los Angeles Area") == ("US", "United States")
    assert normalize_salary_interval("per-year-salary") == "year"
    assert normalize_salary_interval("1 HOUR") == "hour"
    assert decimal_or_none(0) is None


def _transport(payload_file: str) -> httpx.MockTransport:
    payload = (FIXTURE_DIR / payload_file).read_text(encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=json.loads(payload))

    return httpx.MockTransport(handler)


@pytest.mark.asyncio()
async def test_greenhouse_adapter_normalizes_fixture() -> None:
    source = SourceConfig(
        slug="acme-gh",
        name="Acme GH",
        ats="greenhouse",
        company_name="Acme",
        config={"board_token": "acme"},
    )
    async with httpx.AsyncClient(transport=_transport("greenhouse_jobs.json")) as client:
        jobs = await GreenhouseAdapter(client).fetch_jobs(source)

    assert jobs[0].external_job_id == "101"
    assert jobs[0].title == "Backend Engineer"
    assert jobs[0].description_text == "Build Python APIs."
    assert jobs[0].location_country_code == "US"
    assert jobs[0].location_country == "United States"
    assert jobs[0].salary_min == Decimal("120000")
    assert jobs[0].salary_max == Decimal("160000")
    assert jobs[0].salary_currency == "USD"


@pytest.mark.asyncio()
async def test_lever_adapter_normalizes_fixture() -> None:
    source = SourceConfig(
        slug="acme-lever",
        name="Acme Lever",
        ats="lever",
        company_name="Acme",
        config={"site": "acme"},
    )
    async with httpx.AsyncClient(transport=_transport("lever_jobs.json")) as client:
        jobs = await LeverAdapter(client).fetch_jobs(source)

    assert jobs[0].external_job_id == "lev-1"
    assert jobs[0].employment_type == "Full-time"
    assert jobs[0].workplace_type == "hybrid"
    assert jobs[0].location_country_code == "US"
    assert jobs[0].salary_min == Decimal("90000")
    assert jobs[0].salary_max == Decimal("125000")
    assert jobs[0].salary_interval == "year"


@pytest.mark.asyncio()
async def test_ashby_adapter_normalizes_fixture() -> None:
    source = SourceConfig(
        slug="acme-ashby",
        name="Acme Ashby",
        ats="ashby",
        company_name="Acme",
        config={"organization": "acme"},
    )
    async with httpx.AsyncClient(transport=_transport("ashby_jobs.json")) as client:
        jobs = await AshbyAdapter(client).fetch_jobs(source)

    assert jobs[0].external_job_id == "ash-1"
    assert jobs[0].location == "Remote"
    assert jobs[0].description_text == "Own platform services."
    assert jobs[0].location_country_code == "US"
    assert jobs[0].salary_min == Decimal("130000")
    assert jobs[0].salary_max == Decimal("175000")
    assert jobs[0].salary_interval == "year"


@pytest.mark.asyncio()
async def test_adapter_retries_transient_failures() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(503, request=request)
        return httpx.Response(200, json={"jobs": []}, request=request)

    source = SourceConfig(
        slug="acme-gh",
        name="Acme GH",
        ats="greenhouse",
        company_name="Acme",
        config={"board_token": "acme"},
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        jobs = await GreenhouseAdapter(client, max_retries=2, retry_backoff_seconds=0).fetch_jobs(source)

    assert jobs == []
    assert attempts == 3
