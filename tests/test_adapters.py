from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from hunt_board.ingestion.adapters import AshbyAdapter, GreenhouseAdapter, LeverAdapter
from hunt_board.ingestion.sources import SourceConfig


FIXTURE_DIR = Path(__file__).parent / "fixtures"


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

