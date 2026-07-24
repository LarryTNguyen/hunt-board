from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from hunt_board.db.models import JobPosting, JobVersion, ScrapeRun, ScrapeSourceRun, Source
from hunt_board.ingestion.adapters import (
    ADAPTER_REGISTRY,
    AdapterError,
    AshbyAdapter,
    GreenhouseAdapter,
    LeverAdapter,
)
from hunt_board.ingestion.adapters.base import NormalizedJob
from hunt_board.ingestion.lock import IngestionAlreadyRunningError
from hunt_board.ingestion.retention import purge_expired_raw_payloads
from hunt_board.ingestion.sanitizer import sanitize_html, sanitized_description
from hunt_board.ingestion.service import IngestionService
from hunt_board.ingestion.sources import SourceConfig


FIXTURE_DIR = Path(__file__).parent / "fixtures"
SOURCE_FILE = FIXTURE_DIR / "sources_acme.yaml"


class FakeLock:
    def __init__(self, acquired: bool = True) -> None:
        self.can_acquire = acquired
        self.released = False

    def acquire(self, db) -> bool:
        return self.can_acquire

    def release(self) -> None:
        self.released = True


class EmptyAdapter:
    async def fetch_jobs(self, source):
        return []


class StaticAdapter:
    def __init__(self, jobs: list[NormalizedJob]) -> None:
        self.jobs = jobs

    async def fetch_jobs(self, source):
        return self.jobs


class FailingAdapter:
    async def fetch_jobs(self, source):
        raise RuntimeError("offline fixture failure")


def job(*, external_id: str = "1", html: str = "<p>Build APIs.</p>") -> NormalizedJob:
    return NormalizedJob(
        source_slug="acme",
        company_name="Acme",
        external_job_id=external_id,
        title="Backend Engineer",
        location="Remote",
        department="Engineering",
        employment_type="Full-time",
        workplace_type="remote",
        apply_url=f"https://jobs.example.com/{external_id}",
        description_html=html,
        description_text=None,
        raw_json={"description": html},
    )


def test_adapter_registry_is_source_of_truth_for_validation() -> None:
    assert set(ADAPTER_REGISTRY) == {"greenhouse", "lever", "ashby"}
    with pytest.raises(ValidationError, match="unsupported ATS adapter 'workday'"):
        SourceConfig(slug="future", name="Future", ats="workday", company_name="Future")


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    ("adapter_class", "ats", "required_key"),
    [
        (GreenhouseAdapter, "greenhouse", "board_token"),
        (LeverAdapter, "lever", "site"),
        (AshbyAdapter, "ashby", "organization"),
    ],
)
async def test_adapter_config_is_validated_before_request(adapter_class, ats, required_key) -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, json={"jobs": []})

    source = SourceConfig(slug="broken", name="Broken", ats=ats, company_name="Broken")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AdapterError, match=f"config.{required_key}"):
            await adapter_class(client).fetch_jobs(source)
    assert requests == 0


def test_html_sanitizer_keeps_formatting_and_removes_active_content() -> None:
    malicious = """
    <div onclick="steal()"><h2>Role &amp; team</h2><script>alert(1)</script>
      <p>Build <strong>systems</strong>.</p><ul><li>One<li>Two</ul>
      <a href="javascript:alert(1)" onmouseover="steal()">bad</a>
      <a href="https://example.com/job" target="_blank">good</a>
      <iframe src="https://evil.example"></iframe><style>body{display:none}</style>
    </div>
    """
    clean_html, clean_text = sanitized_description(malicious)
    assert "<h2>Role &amp; team</h2>" in clean_html
    assert "<ul><li>One</li><li>Two</li></ul>" in clean_html
    assert "javascript:" not in clean_html
    assert "onclick" not in clean_html
    assert "script" not in clean_html
    assert "alert(1)" not in clean_html
    assert 'href="https://example.com/job"' in clean_html
    assert 'rel="noopener noreferrer"' in clean_html
    assert clean_text == "Role & team Build systems. One Two bad good"
    assert sanitize_html("<p>Malformed <em>but useful") == "<p>Malformed <em>but useful</em></p>"


@pytest.mark.asyncio()
async def test_ingestion_sanitizes_normalized_fields_but_preserves_raw_json(db_session) -> None:
    unsafe = '<p onclick="x()">Hello</p><script>bad()</script>'
    service = IngestionService(
        str(SOURCE_FILE),
        adapter_overrides={"acme": StaticAdapter([job(html=unsafe)])},
    )
    await service.run(db_session, ["acme"])
    posting = db_session.scalar(select(JobPosting))
    version = db_session.scalar(select(JobVersion))
    assert posting.description_html == "<p>Hello</p>"
    assert posting.description_text == "Hello"
    assert posting.raw_json == {"description": unsafe}
    assert version.description_html == "<p>Hello</p>"


@pytest.mark.asyncio()
async def test_lock_contention_creates_no_run_or_source_writes(db_session) -> None:
    lock = FakeLock(acquired=False)
    service = IngestionService(
        str(SOURCE_FILE),
        adapter_overrides={"acme": EmptyAdapter()},
        run_lock=lock,
    )
    with pytest.raises(IngestionAlreadyRunningError):
        await service.run(db_session)
    assert db_session.scalar(select(func.count(ScrapeRun.id))) == 0
    assert db_session.scalar(select(func.count(Source.id))) == 0
    assert lock.released is False
    dry_run = await service.run(db_session, dry_run=True)
    assert dry_run.status == "completed"
    assert db_session.scalar(select(func.count(ScrapeRun.id))) == 0


@pytest.mark.asyncio()
async def test_lock_released_and_run_finalized_after_unexpected_failure(db_session) -> None:
    lock = FakeLock()
    service = IngestionService(str(SOURCE_FILE), run_lock=lock)

    async def explode(*args, **kwargs):
        raise RuntimeError("unexpected persistence failure")

    service._execute_run = explode
    with pytest.raises(RuntimeError, match="unexpected persistence failure"):
        await service.run(db_session)
    run = db_session.scalar(select(ScrapeRun))
    assert lock.released is True
    assert run.status == "failed"
    assert run.finished_at is not None
    assert "unexpected persistence failure" in run.error_message


@pytest.mark.asyncio()
async def test_stale_runs_are_recovered_after_lock_acquisition(db_session) -> None:
    old = datetime.now(timezone.utc) - timedelta(hours=3)
    stale = ScrapeRun(status="running", dry_run=False, sources_requested=["acme"], started_at=old)
    db_session.add(stale)
    db_session.flush()
    db_session.add(ScrapeSourceRun(scrape_run_id=stale.id, source_slug="acme", status="running", started_at=old))
    db_session.commit()
    service = IngestionService(
        str(SOURCE_FILE),
        adapter_overrides={"acme": EmptyAdapter()},
        run_lock=FakeLock(),
        stale_run_minutes=60,
    )
    await service.run(db_session, ["acme"])
    db_session.refresh(stale)
    stale_source = db_session.scalar(select(ScrapeSourceRun).where(ScrapeSourceRun.scrape_run_id == stale.id))
    assert stale.status == "abandoned"
    assert stale_source.status == "abandoned"
    assert stale.finished_at is not None


@pytest.mark.asyncio()
async def test_custom_source_cadence_and_closure_threshold(db_session, tmp_path) -> None:
    source_file = tmp_path / "sources.yaml"
    source_file.write_text(
        """sources:
  - slug: acme
    name: Acme
    ats: greenhouse
    company_name: Acme
    priority: 1
    poll_interval_minutes: 30
    close_after_missed_runs: 2
    config: {board_token: acme}
""",
        encoding="utf-8",
    )
    first = IngestionService(str(source_file), adapter_overrides={"acme": StaticAdapter([job()])})
    await first.run(db_session, ["acme"])
    source = db_session.scalar(select(Source))
    assert source.poll_interval_minutes == 30
    assert source.close_after_missed_runs == 2
    next_due = source.next_due_at
    if next_due.tzinfo is None:
        next_due = next_due.replace(tzinfo=timezone.utc)
    assert timedelta(minutes=29) <= next_due - datetime.now(timezone.utc) <= timedelta(minutes=30)

    empty = IngestionService(str(source_file), adapter_overrides={"acme": EmptyAdapter()})
    await empty.run(db_session, ["acme"])
    posting = db_session.scalar(select(JobPosting))
    assert posting.active is True
    assert posting.consecutive_missed_runs == 1
    await empty.run(db_session, ["acme"])
    assert posting.active is False
    assert posting.consecutive_missed_runs == 2


@pytest.mark.asyncio()
async def test_failed_source_does_not_advance_missed_run_state(db_session) -> None:
    first = IngestionService(str(SOURCE_FILE), adapter_overrides={"acme": StaticAdapter([job()])})
    await first.run(db_session, ["acme"])
    await IngestionService(str(SOURCE_FILE), adapter_overrides={"acme": FailingAdapter()}).run(db_session, ["acme"])
    posting = db_session.scalar(select(JobPosting))
    assert posting.active is True
    assert posting.consecutive_missed_runs == 0


def test_raw_payload_cleanup_dry_run_real_and_idempotent(db_session) -> None:
    source = Source(slug="acme", name="Acme", ats="greenhouse", company_name="Acme")
    db_session.add(source)
    db_session.flush()
    expired = datetime.now(timezone.utc) - timedelta(days=1)
    future = datetime.now(timezone.utc) + timedelta(days=1)
    posting = JobPosting(
        source_id=source.id,
        source_slug="acme",
        company_name="Acme",
        external_job_id="1",
        title="Engineer",
        normalized_title="engineer",
        raw_json={"secret": "payload"},
        raw_json_expires_at=expired,
    )
    current = JobPosting(
        source_id=source.id,
        source_slug="acme",
        company_name="Acme",
        external_job_id="2",
        title="Designer",
        normalized_title="designer",
        raw_json={"keep": True},
        raw_json_expires_at=future,
    )
    db_session.add_all([posting, current])
    db_session.flush()
    version = JobVersion(
        job_posting_id=posting.id,
        description_hash="a" * 64,
        raw_json={"version": "payload"},
        raw_json_expires_at=expired,
    )
    db_session.add(version)
    db_session.commit()

    dry = purge_expired_raw_payloads(db_session, dry_run=True)
    assert (dry.postings_considered, dry.versions_considered) == (1, 1)
    assert posting.raw_json == {"secret": "payload"}
    real = purge_expired_raw_payloads(db_session)
    assert (real.postings_purged, real.versions_purged) == (1, 1)
    assert posting.raw_json == {}
    assert version.raw_json == {}
    assert current.raw_json == {"keep": True}
    repeat = purge_expired_raw_payloads(db_session)
    assert (repeat.postings_considered, repeat.versions_considered) == (0, 0)


def test_jobs_searches_description_and_ignores_whitespace(client, db_session) -> None:
    source = Source(slug="acme", name="Acme", ats="greenhouse", company_name="Acme")
    db_session.add(source)
    db_session.flush()
    db_session.add_all(
        [
            JobPosting(
                source_id=source.id,
                source_slug="acme",
                company_name="Acme",
                external_job_id="1",
                title="Engineer",
                normalized_title="engineer",
                location="Remote",
                normalized_location="remote",
                description_text="Build observability pipelines",
                raw_json={},
            ),
            JobPosting(
                source_id=source.id,
                source_slug="acme",
                company_name="Acme",
                external_job_id="2",
                title="Designer",
                normalized_title="designer",
                location="Seattle",
                normalized_location="seattle",
                description_text="Design product flows",
                raw_json={},
            ),
        ]
    )
    db_session.commit()
    assert [item["title"] for item in client.get("/jobs?search=observability").json()] == ["Engineer"]
    assert len(client.get("/jobs?search=%20%20%20").json()) == 2
    assert client.get("/jobs?search=Seattle").json()[0]["title"] == "Designer"
    assert len(client.get("/jobs?search=Engineer").json()) == 1
    assert len(client.get("/jobs?search=Acme").json()) == 2


def test_ingestion_health_reports_ok_degraded_and_stale(client, db_session) -> None:
    response = client.get("/health/ingestion")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    source = Source(
        slug="acme",
        name="Acme",
        ats="greenhouse",
        company_name="Acme",
        health_status="unhealthy",
    )
    db_session.add(source)
    db_session.commit()
    assert client.get("/health/ingestion").json()["status"] == "degraded"
    stale = ScrapeRun(
        status="running",
        dry_run=False,
        sources_requested=[],
        started_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    db_session.add(stale)
    db_session.commit()
    payload = client.get("/health/ingestion").json()
    assert payload["status"] == "stale"
    assert payload["stale_running_runs"] == 1
    assert payload["run_in_progress"] is False


def test_admin_ingestion_returns_conflict_for_lock_contention(client, db_session, monkeypatch) -> None:
    async def reject(*args, **kwargs):
        raise IngestionAlreadyRunningError("already running")

    monkeypatch.setattr("hunt_board.admin.api.IngestionService.run", reject)
    response = client.post("/admin/ingestion/run", json={})
    assert response.status_code == 409
    legacy_response = client.post("/api/admin/ingestion/run", json={})
    assert legacy_response.status_code == 409

    source = Source(slug="acme", name="Acme", ats="greenhouse", company_name="Acme")
    db_session.add(source)
    db_session.commit()
    source_response = client.post(f"/admin/ingestion/run-source/{source.id}")
    assert source_response.status_code == 409
