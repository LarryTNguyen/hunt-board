from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import select

from hunt_board.db.models import JobPosting, JobVersion
from hunt_board.ingestion.adapters import (
    ADAPTER_REGISTRY,
    AdapterError,
    AdapterFetchResult,
    WorkdayAdapter,
)
from hunt_board.ingestion.adapters.workday import parse_workday_posted_at
from hunt_board.ingestion.service import IngestionService
from hunt_board.ingestion.sources import SourceConfig


FIXTURES = Path(__file__).parent / "fixtures"
HOST = "example.wd5.myworkdayjobs.com"


def payload(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def source(**updates) -> SourceConfig:
    values = {
        "slug": "example-workday",
        "name": "Example Workday",
        "ats": "workday",
        "company_name": "Configured Company",
        "careers_url": f"https://{HOST}/en-US/External",
        "config": {
            "host": HOST,
            "tenant": "example",
            "site": "External",
            "page_size": 1,
            "detail_concurrency": 2,
            "request_interval_ms": 0,
            "max_jobs": 10,
        },
    }
    values.update(updates)
    return SourceConfig(**values)


def normal_handler(request: httpx.Request) -> httpx.Response:
    if request.method == "POST":
        body = json.loads(request.content)
        page = "workday_jobs_page_1.json" if body["offset"] == 0 else "workday_jobs_page_2.json"
        return httpx.Response(200, json=payload(page), request=request)
    if "Software-Engineer" in request.url.path:
        return httpx.Response(200, json=payload("workday_job_detail.json"), request=request)
    return httpx.Response(200, json=payload("workday_job_detail_remote.json"), request=request)


def test_workday_is_registered_and_config_is_validated() -> None:
    assert "workday" in ADAPTER_REGISTRY
    with pytest.raises(ValidationError, match="config.host"):
        SourceConfig(
            slug="broken",
            name="Broken",
            ats="workday",
            company_name="Broken",
            careers_url=f"https://{HOST}/External",
        )


@pytest.mark.parametrize(
    ("host", "careers_url"),
    [
        ("example.com", "https://example.com/External"),
        ("127.0.0.1", "https://127.0.0.1/External"),
        ("https://example.wd5.myworkdayjobs.com", f"https://{HOST}/External"),
        (HOST, "https://other.wd5.myworkdayjobs.com/External"),
    ],
)
def test_workday_rejects_unsafe_hosts(host: str, careers_url: str) -> None:
    with pytest.raises(ValidationError):
        source(
            careers_url=careers_url,
            config={"host": host, "tenant": "example", "site": "External"},
        )


@pytest.mark.parametrize("segment", ["../tenant", "a/b", "https:evil", "bad?query"])
def test_workday_rejects_unsafe_tenant_and_site_segments(segment: str) -> None:
    with pytest.raises(ValidationError):
        source(config={"host": HOST, "tenant": segment, "site": "External"})


@pytest.mark.asyncio
async def test_workday_paginates_posts_exact_payload_and_normalizes_details() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return normal_handler(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        jobs = await WorkdayAdapter(client).fetch_jobs(source())

    assert [job.external_job_id for job in jobs] == [
        "0123456789abcdef0123456789abcdef",
        "fedcba9876543210fedcba9876543210",
    ]
    listing_requests = [request for request in requests if request.method == "POST"]
    assert [json.loads(request.content)["offset"] for request in listing_requests] == [0, 1]
    assert json.loads(listing_requests[0].content) == {
        "appliedFacets": {},
        "limit": 1,
        "offset": 0,
        "searchText": "",
    }
    assert listing_requests[0].headers["accept-language"] == "en-US"
    assert listing_requests[0].headers["referer"] == f"https://{HOST}/en-US/External"
    assert jobs[0].company_name == "Configured Company"
    assert jobs[0].posted_at == datetime(2026, 7, 22, tzinfo=timezone.utc)
    assert jobs[0].workplace_type == "hybrid"
    assert [item["display"] for item in jobs[0].locations] == ["Seattle, WA", "Austin, TX"]
    assert jobs[1].location_country_code == "JP"
    assert jobs[1].location_country == "Japan"
    assert jobs[1].posted_at is None
    assert jobs[0].raw_json == {
        "listing": payload("workday_jobs_page_1.json")["jobPostings"][0],
        "detail": payload("workday_job_detail.json"),
    }


@pytest.mark.asyncio
async def test_workday_empty_board_is_complete_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload("workday_jobs_empty.json"), request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await WorkdayAdapter(client).fetch_jobs(source()) == []


@pytest.mark.asyncio
async def test_workday_accepts_zero_total_on_noninitial_nonempty_page() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            body = json.loads(request.content)
            page_name = (
                "workday_jobs_page_1.json"
                if body["offset"] == 0
                else "workday_jobs_page_2.json"
            )
            data = payload(page_name)
            if body["offset"] > 0:
                data["total"] = 0
            return httpx.Response(200, json=data, request=request)
        return normal_handler(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        jobs = await WorkdayAdapter(client).fetch_jobs(source())

    assert [job.external_job_id for job in jobs] == [
        "0123456789abcdef0123456789abcdef",
        "fedcba9876543210fedcba9876543210",
    ]


@pytest.mark.asyncio
async def test_workday_rejects_zero_total_on_noninitial_empty_page() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        body = json.loads(request.content)
        if body["offset"] == 0:
            return httpx.Response(
                200,
                json=payload("workday_jobs_page_1.json"),
                request=request,
            )
        return httpx.Response(
            200,
            json={"total": 0, "jobPostings": []},
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AdapterError, match="remained incomplete"):
            await WorkdayAdapter(client).fetch_jobs(source())

    assert calls == 4


@pytest.mark.asyncio
async def test_workday_retries_incomplete_listing_then_fails() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        response = {"total": 2, "jobPostings": []}
        return httpx.Response(200, json=response, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AdapterError, match="remained incomplete"):
            await WorkdayAdapter(client).fetch_jobs(source())
    assert calls == 2


@pytest.mark.asyncio
async def test_workday_rejects_duplicates_and_max_jobs_without_truncation() -> None:
    duplicate = payload("workday_jobs_page_1.json")["jobPostings"][0]

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["offset"] == 0:
            data = {"total": 2, "jobPostings": [duplicate]}
        else:
            data = {"total": 2, "jobPostings": [duplicate]}
        return httpx.Response(200, json=data, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AdapterError, match="remained incomplete"):
            await WorkdayAdapter(client).fetch_jobs(source())

    def too_large(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"total": 11, "jobPostings": []}, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(too_large)) as client:
        with pytest.raises(AdapterError, match="max_jobs"):
            await WorkdayAdapter(client).fetch_jobs(source())


@pytest.mark.asyncio
async def test_workday_honors_retry_after_and_classifies_non_json() -> None:
    attempts = 0
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "2"}, request=request)
        return httpx.Response(200, json=payload("workday_jobs_empty.json"), request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await WorkdayAdapter(client, max_retries=1, sleep=fake_sleep).fetch_jobs(source()) == []
    assert sleeps == [2]

    def html_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>blocked</html>", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(html_handler)) as client:
        with pytest.raises(AdapterError, match="expected JSON"):
            await WorkdayAdapter(client).fetch_jobs(source())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "message"),
    [
        (403, "unavailable or blocked"),
        (404, "check host, tenant, and site"),
        (422, "unsupported"),
    ],
)
async def test_workday_classifies_persistent_listing_errors(status: int, message: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AdapterError, match=message):
            await WorkdayAdapter(client).fetch_jobs(source())


@pytest.mark.asyncio
async def test_workday_detail_concurrency_is_bounded_and_order_is_stable() -> None:
    postings = [
        {"title": f"Role {index}", "externalPath": f"/job/Place/Role-{index}"}
        for index in range(6)
    ]
    active = 0
    maximum_active = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, maximum_active
        if request.method == "POST":
            return httpx.Response(
                200,
                json={"total": len(postings), "jobPostings": postings},
                request=request,
            )
        index = int(request.url.path.rsplit("-", 1)[1])
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep((len(postings) - index) / 1000)
        active -= 1
        return httpx.Response(
            200,
            json={
                "jobPostingInfo": {
                    "id": f"id-{index}",
                    "title": f"Role {index}",
                    "location": "Remote",
                    "posted": True,
                }
            },
            request=request,
        )

    configured = source(
        config={
            "host": HOST,
            "tenant": "example",
            "site": "External",
            "page_size": 20,
            "detail_concurrency": 2,
            "request_interval_ms": 0,
            "max_jobs": 10,
        }
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        jobs = await WorkdayAdapter(client).fetch_jobs(configured)
    assert maximum_active == 2
    assert [job.external_job_id for job in jobs] == [f"id-{index}" for index in range(6)]


@pytest.mark.asyncio
async def test_workday_supports_myworkdaysite_family_and_identity_fallback() -> None:
    site_host = "example.wd1.myworkdaysite.com"
    configured = source(
        careers_url=f"https://{site_host}/en-US/External",
        config={
            "host": site_host,
            "tenant": "example",
            "site": "External",
            "request_interval_ms": 0,
        },
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "total": 1,
                    "jobPostings": [
                        {
                            "title": "Site Reliability Engineer",
                            "externalPath": "/job/Remote/Site-Reliability-Engineer",
                        }
                    ],
                },
                request=request,
            )
        return httpx.Response(
            200,
            json=payload("workday_job_detail_myworkdaysite.json"),
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        jobs = await WorkdayAdapter(client).fetch_jobs(configured)
    assert jobs[0].external_job_id == "SITE-789"
    assert jobs[0].workplace_type == "remote"
    assert jobs[0].location_country_code == "CA"


@pytest.mark.asyncio
async def test_workday_reconciles_a_withdrawn_detail() -> None:
    listing_scans = 0
    detail_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal listing_scans, detail_calls
        if request.method == "POST":
            listing_scans += 1
            data = payload("workday_jobs_page_1.json") if listing_scans == 1 else payload("workday_jobs_empty.json")
            if listing_scans == 1:
                data = {**data, "total": 1}
            return httpx.Response(200, json=data, request=request)
        detail_calls += 1
        return httpx.Response(404, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        jobs = await WorkdayAdapter(client).fetch_jobs(source())
    assert jobs == []
    assert listing_scans == 2
    assert detail_calls == 1


@pytest.mark.asyncio
async def test_workday_still_listed_missing_detail_returns_partial_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            data = {**payload("workday_jobs_page_1.json"), "total": 1}
            return httpx.Response(200, json=data, request=request)
        return httpx.Response(404, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await WorkdayAdapter(client).fetch_jobs(source())

    assert isinstance(result, AdapterFetchResult)
    assert result.jobs == []
    assert result.lifecycle_authoritative is False
    assert result.skipped_count == 1
    assert "lifecycle closure was suppressed" in (result.warning_message or "")


@pytest.mark.asyncio
async def test_workday_partial_result_keeps_complete_details() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return normal_handler(request)
        if "Software-Engineer" in request.url.path:
            return httpx.Response(404, request=request)
        return normal_handler(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await WorkdayAdapter(client).fetch_jobs(source())

    assert isinstance(result, AdapterFetchResult)
    assert [job.external_job_id for job in result.jobs] == [
        "fedcba9876543210fedcba9876543210"
    ]
    assert result.lifecycle_authoritative is False
    assert result.skipped_count == 1
    assert "/job/Seattle-WA/Software-Engineer_REQ-123" in (
        result.warning_message or ""
    )


def test_workday_relative_dates_are_conservative() -> None:
    scan = datetime(2026, 7, 24, 18, tzinfo=timezone.utc)
    assert parse_workday_posted_at("Posted Today", scan) == datetime(2026, 7, 24, tzinfo=timezone.utc)
    assert parse_workday_posted_at("Posted Yesterday", scan) == datetime(2026, 7, 23, tzinfo=timezone.utc)
    assert parse_workday_posted_at("Posted 3 Days Ago", scan) == datetime(2026, 7, 21, tzinfo=timezone.utc)
    assert parse_workday_posted_at("Posted 30+ Days Ago", scan) is None


@pytest.mark.asyncio
async def test_workday_uses_normal_ingestion_sanitization_and_is_idempotent(
    db_session,
    tmp_path,
) -> None:
    source_file = tmp_path / "sources.yaml"
    source_file.write_text(
        f"""sources:
  - slug: example-workday
    name: Example Workday
    ats: workday
    company_name: Configured Company
    careers_url: https://{HOST}/en-US/External
    enabled: false
    close_after_missed_runs: 12
    config:
      host: {HOST}
      tenant: example
      site: External
      page_size: 1
      detail_concurrency: 2
      request_interval_ms: 0
      max_jobs: 10
""",
        encoding="utf-8",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(normal_handler)) as client:
        adapter = WorkdayAdapter(client)
        service = IngestionService(
            str(source_file),
            adapter_overrides={"example-workday": adapter},
        )
        first = await service.run(db_session, ["example-workday"])
        second = await service.run(db_session, ["example-workday"])

    jobs = db_session.scalars(select(JobPosting).order_by(JobPosting.id)).all()
    assert first.total_new_jobs == 2
    assert second.total_unchanged_jobs == 2
    assert len(jobs) == 2
    assert len(db_session.scalars(select(JobVersion)).all()) == 2
    assert "script" not in (jobs[0].description_html or "")
    assert "alert" not in (jobs[0].description_text or "")
    assert [item["display"] for item in jobs[0].locations_json] == ["Seattle, WA", "Austin, TX"]
    assert jobs[0].raw_json_expires_at is not None
