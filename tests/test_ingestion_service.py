from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from hunt_board.db.models import DuplicateReview, JobPosting, JobVersion, ScrapeRun, Source
from hunt_board.ingestion.adapters.base import NormalizedJob
from hunt_board.ingestion.service import IngestionService

FIXTURE_DIR = Path(__file__).parent / "fixtures"
SOURCE_FILE = FIXTURE_DIR / "sources_acme.yaml"


class FakeAdapter:
    def __init__(self, jobs: list[NormalizedJob]) -> None:
        self.jobs = jobs

    async def fetch_jobs(self, source):
        return self.jobs


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
async def test_possible_duplicate_creates_review(db_session) -> None:
    service = IngestionService(str(SOURCE_FILE), adapter_overrides={"acme": FakeAdapter([_job("1"), _job("2")])})

    await service.run(db_session)

    review = db_session.scalar(select(DuplicateReview))
    assert review is not None
