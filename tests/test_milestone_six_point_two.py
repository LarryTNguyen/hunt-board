from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from hunt_board.core.config import get_settings, validate_runtime_settings
from hunt_board.core.observability import sanitized
from hunt_board.db.models import (
    IngestionQuarantine,
    JobLifecycleEvent,
    JobPosting,
    ScrapeRun,
    ScrapeSourceRun,
    Source,
)
from hunt_board.ingestion.adapters.base import HttpATSAdapter, NormalizedJob
from hunt_board.ingestion.service import IngestionService


SOURCE_FILE = Path(__file__).parent / "fixtures" / "sources_acme.yaml"


class NeverLock:
    def acquire(self, _db) -> bool:
        return False

    def release(self) -> None:
        pass


class JobsAdapter:
    def __init__(self, jobs):
        self.jobs = jobs

    async def fetch_jobs(self, _source):
        return self.jobs


def normalized(external_id: str, title: str = "Engineer", *, closed: bool = False) -> NormalizedJob:
    return NormalizedJob(
        source_slug="acme",
        company_name="Acme",
        external_job_id=external_id,
        title=title,
        location="Remote, United States",
        department="Engineering",
        employment_type="Full-time",
        workplace_type="Remote",
        apply_url=f"https://jobs.example.test/{external_id}",
        description_html="<p>Role</p>",
        description_text="Role",
        raw_json={"id": external_id},
        explicitly_closed=closed,
    )


def posting(source: Source, external_id: str, *, first_seen_at: datetime | None = None) -> JobPosting:
    now = datetime.now(timezone.utc)
    return JobPosting(
        source_id=source.id,
        source_slug=source.slug,
        company_name=source.company_name,
        external_job_id=external_id,
        title=f"Engineer {external_id}",
        normalized_title=f"engineer {external_id}",
        location="Remote, United States",
        normalized_location="remote united states",
        raw_json={},
        first_seen_at=first_seen_at or now,
        last_seen_at=now,
    )


def test_environment_safety_rejects_unsafe_production() -> None:
    unsafe = replace(get_settings(), environment="production", release="development")
    with pytest.raises(RuntimeError, match="Unsafe production configuration"):
        validate_runtime_settings(unsafe)
    with pytest.raises(ValueError, match="development, test, staging, or production"):
        validate_runtime_settings(replace(get_settings(), environment="preview"))


@pytest.mark.asyncio
async def test_one_pending_and_further_triggers_coalesce(db_session) -> None:
    service = IngestionService(
        str(SOURCE_FILE),
        run_lock=NeverLock(),
        queue_on_contention=True,
    )
    first = await service.run(db_session, ["acme"], triggered_by="api")
    second = await service.run(db_session, ["acme"], triggered_by="cron")
    assert first.status == "pending"
    assert second.status == "coalesced"
    assert first.scrape_run_id == second.scrape_run_id
    pending = list(db_session.scalars(select(ScrapeRun).where(ScrapeRun.status == "pending")))
    assert len(pending) == 1
    assert pending[0].coalesced_triggers == 1


def test_cancel_pending_and_recover_stale_runs(client, db_session) -> None:
    now = datetime.now(timezone.utc)
    pending = ScrapeRun(status="pending", sources_requested=["acme"])
    stale = ScrapeRun(
        status="running",
        sources_requested=["acme"],
        started_at=now - timedelta(hours=3),
    )
    db_session.add_all([pending, stale])
    db_session.flush()
    source_run = ScrapeSourceRun(
        scrape_run_id=stale.id,
        source_slug="acme",
        status="running",
        started_at=stale.started_at,
    )
    db_session.add(source_run)
    db_session.commit()
    cancelled = client.post(f"/admin/scrape-runs/{pending.id}/cancel")
    assert cancelled.status_code == 200
    assert db_session.get(ScrapeRun, pending.id).status == "cancelled"
    recovered = client.post("/admin/ingestion/recover-stale").json()
    assert recovered["recovered_runs"] == 1
    assert db_session.get(ScrapeRun, stale.id).status == "abandoned"
    assert db_session.get(ScrapeSourceRun, source_run.id).status == "abandoned"


@pytest.mark.asyncio
async def test_retry_timeout_uses_three_total_attempts() -> None:
    attempts = 0

    async def timeout(_request):
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("offline timeout")

    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
        adapter = HttpATSAdapter(
            client,
            max_retries=2,
            retry_backoff_seconds=0,
            retry_jitter_seconds=0,
        )
        with pytest.raises(Exception, match="3 attempt"):
            await adapter.get_json("https://example.test/jobs")
    assert attempts == 3
    assert adapter.retry_count == 2
    assert adapter.timeout_count == 3


def test_three_misses_one_year_and_explicit_closure_are_audited(db_session) -> None:
    source = Source(slug="acme", name="Acme", ats="greenhouse", company_name="Acme")
    db_session.add(source)
    db_session.flush()
    missed = posting(source, "missed")
    aged = posting(source, "aged", first_seen_at=datetime.now(timezone.utc) - timedelta(days=366))
    explicit = posting(source, "explicit")
    db_session.add_all([missed, aged, explicit])
    db_session.flush()
    service = IngestionService(str(SOURCE_FILE))
    assert service._mark_closed(db_session, source, {"missed", "aged", "explicit"}, 3) == 1
    assert aged.active is False
    assert service._close_explicit_job(db_session, source, "explicit", None) == 1
    for _ in range(2):
        assert service._mark_closed(db_session, source, set(), 3) == 0
    assert service._mark_closed(db_session, source, set(), 3) == 1
    assert missed.active is False
    reasons = set(db_session.scalars(select(JobLifecycleEvent.reason)))
    assert any("maximum age" in reason for reason in reasons)
    assert "source explicitly reported closed" in reasons
    assert any("3 successful scans" in reason for reason in reasons)


@pytest.mark.asyncio
async def test_quarantine_blocks_mass_deactivation_and_missed_evidence(db_session) -> None:
    source = Source(
        slug="acme",
        name="Acme",
        ats="greenhouse",
        company_name="Acme",
        last_successful_job_count=5,
    )
    db_session.add(source)
    db_session.flush()
    jobs = [posting(source, str(index)) for index in range(5)]
    db_session.add_all(jobs)
    db_session.commit()
    service = IngestionService(
        str(SOURCE_FILE),
        adapter_overrides={"acme": JobsAdapter([])},
        anomaly_zero_quarantine=True,
    )
    summary = await service.run(db_session, ["acme"])
    assert summary.status == "completed_with_errors"
    assert summary.source_runs[0].status == "quarantined"
    assert all(job.active and job.consecutive_missed_runs == 0 for job in jobs)
    quarantine = db_session.scalar(select(IngestionQuarantine))
    assert quarantine.status == "pending"
    assert quarantine.diff_summary["attempted_deactivation_ratio"] == 1.0
    assert "description" not in quarantine.diff_summary


@pytest.mark.asyncio
async def test_reappearance_reactivates_same_record_with_history(db_session) -> None:
    source = Source(slug="acme", name="Acme", ats="greenhouse", company_name="Acme")
    db_session.add(source)
    db_session.flush()
    existing = posting(source, "same")
    existing.active = False
    existing.closed_at = datetime.now(timezone.utc) - timedelta(days=2)
    db_session.add(existing)
    db_session.commit()
    existing_id = existing.id
    service = IngestionService(
        str(SOURCE_FILE),
        adapter_overrides={"acme": JobsAdapter([normalized("same")])},
    )
    await service.run(db_session, ["acme"])
    refreshed = db_session.get(JobPosting, existing_id)
    assert refreshed.active is True and refreshed.closed_at is None
    assert db_session.scalar(select(JobLifecycleEvent.event_type)) == "reactivated"


def test_redaction_and_deployment_document_contracts() -> None:
    redacted = sanitized(
        {
            "error": "Bearer abc.def email owner@example.com https://x.test?a=1&token=secret",
            "description": "private body",
        }
    )
    assert "abc.def" not in redacted["error"]
    assert "owner@example.com" not in redacted["error"]
    assert "token=secret" not in redacted["error"]
    assert redacted["description"] == "[REDACTED]"
    root = Path(__file__).parents[1]
    deployment = (root / "docs" / "deployment.md").read_text(encoding="utf-8")
    checklist = (root / "docs" / "owner-ui-checklist-6.2.md").read_text(encoding="utf-8")
    assert all(term in deployment for term in ("alembic upgrade head", "rollback", "backup", "$7–$17"))
    assert all(f"## {step}." in checklist for step in range(1, 17))
    assert "17 */2 * * *" in (root / ".github" / "workflows" / "ingestion-cron.yml").read_text(encoding="utf-8")


def test_operations_ui_contract_has_queue_quarantine_and_correlation(client) -> None:
    page = client.get("/app/operations.html")
    script = client.get("/app/assets/pages/operations.js")
    assert page.status_code == 200
    assert all(
        marker in page.text
        for marker in ("data-deployment", "data-queue-state", "data-quarantine-list", "data-correlation-form")
    )
    assert all(
        marker in script.text
        for marker in ("api.cancelRun", "api.retryFailedSources", "api.approveQuarantine", "api.correlationLookup")
    )
