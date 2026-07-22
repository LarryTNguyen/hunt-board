from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from hunt_board.db.models import DuplicateReview, JobPosting, JobVersion, ScrapeRun, ScrapeSourceRun, Source
from hunt_board.ingestion.adapters.base import NormalizedJob
from hunt_board.ingestion.service import IngestionService

FIXTURE_DIR = Path(__file__).parent / "fixtures"
SOURCE_FILE = FIXTURE_DIR / "sources_acme.yaml"


class FakeAdapter:
    def __init__(self, jobs: list[NormalizedJob]) -> None:
        self.jobs = jobs

    async def fetch_jobs(self, source):
        return self.jobs


class FailingAdapter:
    async def fetch_jobs(self, source):
        raise RuntimeError("fixture source unavailable")


class ConcurrentAdapter:
    def __init__(self, tracker: dict[str, int]) -> None:
        self.tracker = tracker

    async def fetch_jobs(self, source):
        self.tracker["active"] += 1
        self.tracker["maximum"] = max(self.tracker["maximum"], self.tracker["active"])
        await asyncio.sleep(0.02)
        self.tracker["active"] -= 1
        return []


def _job(external_id: str = "1", title: str = "Backend Engineer") -> NormalizedJob:
    return NormalizedJob(
        source_slug="acme",
        company_name="Acme",
        external_job_id=external_id,
        title=title,
        location="Remote, United States",
        department="Engineering",
        employment_type="Full-time",
        workplace_type="remote",
        apply_url=f"https://jobs.example.com/{external_id}",
        description_html="<p>Build APIs.</p>",
        description_text="Build APIs.",
        raw_json={"id": external_id},
        location_country_code="US",
        location_country="United States",
        salary_min=Decimal("100000"),
        salary_max=Decimal("140000"),
        salary_currency="USD",
        salary_interval="year",
    )


@pytest.mark.asyncio()
async def test_dry_run_does_not_write(db_session) -> None:
    service = IngestionService(
        str(SOURCE_FILE),
        adapter_overrides={"acme": FakeAdapter([_job()])},
    )

    summary = await service.run(db_session, dry_run=True)

    assert summary.total_fetched == 1
    assert summary.total_upserted == 1
    assert db_session.scalar(select(Source)) is None
    assert db_session.scalar(select(JobPosting)) is None
    assert db_session.scalar(select(ScrapeRun)) is None


@pytest.mark.asyncio()
async def test_ingestion_writes_metrics_and_marks_closed(db_session) -> None:
    service = IngestionService(str(SOURCE_FILE), adapter_overrides={"acme": FakeAdapter([_job("1"), _job("2")])})

    first = await service.run(db_session)

    assert first.total_fetched == 2
    assert db_session.scalar(select(ScrapeRun)).status == "completed"
    assert len(db_session.scalars(select(JobPosting)).all()) == 2
    stored = db_session.scalar(select(JobPosting).where(JobPosting.external_job_id == "1"))
    assert stored.location_country_code == "US"
    assert stored.location_country == "United States"
    assert stored.salary_min == Decimal("100000")
    assert stored.salary_max == Decimal("140000")
    assert stored.salary_currency == "USD"
    assert stored.salary_interval == "year"
    assert stored.source.company_logo_url == "https://example.com/acme-logo.svg"

    service = IngestionService(str(SOURCE_FILE), adapter_overrides={"acme": FakeAdapter([_job("1")])})
    for _ in range(11):
        interim = await service.run(db_session, ["acme"])
        assert interim.total_closed == 0
    second = await service.run(db_session, ["acme"])

    assert second.total_closed == 1
    inactive = db_session.scalar(select(JobPosting).where(JobPosting.external_job_id == "2"))
    assert inactive.active is False
    assert inactive.consecutive_missed_runs == 12


@pytest.mark.asyncio()
async def test_description_changes_create_versions(db_session) -> None:
    first_job = _job("1")
    service = IngestionService(str(SOURCE_FILE), adapter_overrides={"acme": FakeAdapter([first_job])})
    await service.run(db_session, ["acme"])

    changed = NormalizedJob(
        **{**first_job.__dict__, "description_html": "<p>Build better APIs.</p>", "description_text": "Build better APIs."}
    )
    service = IngestionService(str(SOURCE_FILE), adapter_overrides={"acme": FakeAdapter([changed])})
    await service.run(db_session, ["acme"])

    assert len(db_session.scalars(select(JobVersion)).all()) == 2


@pytest.mark.asyncio()
async def test_repeated_job_is_counted_unchanged_without_an_upsert(db_session) -> None:
    service = IngestionService(str(SOURCE_FILE), adapter_overrides={"acme": FakeAdapter([_job()])})
    await service.run(db_session, ["acme"])

    second = await service.run(db_session, ["acme"])

    assert second.total_new_jobs == 0
    assert second.total_updated_jobs == 0
    assert second.total_unchanged_jobs == 1
    assert second.total_upserted == 0
    assert len(db_session.scalars(select(JobVersion)).all()) == 1
    run = db_session.scalar(select(ScrapeRun).order_by(ScrapeRun.id.desc()))
    source_run = db_session.scalar(
        select(ScrapeSourceRun).where(ScrapeSourceRun.scrape_run_id == run.id)
    )
    assert run.total_unchanged_jobs == 1
    assert source_run.unchanged_jobs == 1


@pytest.mark.asyncio()
async def test_changed_job_is_updated(db_session) -> None:
    service = IngestionService(str(SOURCE_FILE), adapter_overrides={"acme": FakeAdapter([_job()])})
    await service.run(db_session, ["acme"])

    changed = _job(title="Senior Backend Engineer")
    changed_summary = await IngestionService(
        str(SOURCE_FILE), adapter_overrides={"acme": FakeAdapter([changed])}
    ).run(db_session, ["acme"])

    assert changed_summary.total_updated_jobs == 1
    assert changed_summary.total_unchanged_jobs == 0
    assert db_session.scalar(select(JobPosting)).title == "Senior Backend Engineer"


@pytest.mark.asyncio()
async def test_failed_source_records_health_metadata(db_session) -> None:
    summary = await IngestionService(
        str(SOURCE_FILE), adapter_overrides={"acme": FailingAdapter()}
    ).run(db_session, ["acme"])

    source = db_session.scalar(select(Source).where(Source.slug == "acme"))
    assert summary.status == "failed"
    assert summary.source_runs[0].error_message == "fixture source unavailable"
    assert source.last_checked_at is not None
    assert source.last_error == "fixture source unavailable"
    assert source.consecutive_failures == 1


@pytest.mark.asyncio()
async def test_source_fetches_respect_global_concurrency_limit(db_session, tmp_path) -> None:
    source_file = tmp_path / "sources.yaml"
    source_file.write_text(
        """sources:
  - {slug: one, name: One, ats: greenhouse, company_name: One, config: {board_token: one}}
  - {slug: two, name: Two, ats: lever, company_name: Two, config: {site: two}}
  - {slug: three, name: Three, ats: ashby, company_name: Three, config: {organization: three}}
""",
        encoding="utf-8",
    )
    tracker = {"active": 0, "maximum": 0}
    service = IngestionService(
        str(source_file),
        source_concurrency=2,
        adapter_overrides={slug: ConcurrentAdapter(tracker) for slug in ("one", "two", "three")},
    )

    summary = await service.run(db_session, dry_run=True)

    assert summary.status == "completed"
    assert tracker["maximum"] == 2


@pytest.mark.asyncio()
async def test_source_failure_does_not_stop_other_sources(db_session, tmp_path) -> None:
    source_file = tmp_path / "sources.yaml"
    source_file.write_text(
        """sources:
  - {slug: broken, name: Broken, ats: greenhouse, company_name: Broken, config: {board_token: broken}}
  - {slug: working, name: Working, ats: lever, company_name: Acme, config: {site: working}}
""",
        encoding="utf-8",
    )
    service = IngestionService(
        str(source_file),
        adapter_overrides={"broken": FailingAdapter(), "working": FakeAdapter([_job()])},
    )

    summary = await service.run(db_session)

    assert summary.status == "completed_with_errors"
    assert summary.total_errors == 1
    assert summary.total_new_jobs == 1
    assert db_session.scalar(select(JobPosting)).source_slug == "working"


@pytest.mark.asyncio()
async def test_possible_duplicate_creates_review(db_session) -> None:
    service = IngestionService(str(SOURCE_FILE), adapter_overrides={"acme": FakeAdapter([_job("1"), _job("2")])})

    await service.run(db_session)

    review = db_session.scalar(select(DuplicateReview))
    assert review is not None
