from __future__ import annotations

from datetime import datetime, timedelta, timezone

from hunt_board.db.models import JobPosting, ScrapeRun, Source


def test_liveness_readiness_and_operations_aggregate(client, db_session) -> None:
    now = datetime.now(timezone.utc)
    source = Source(
        slug="acme",
        name="Acme",
        ats="greenhouse",
        company_name="Acme",
        health_status="unhealthy",
        next_due_at=now - timedelta(minutes=1),
    )
    db_session.add(source)
    db_session.flush()
    db_session.add_all(
        [
            JobPosting(source_id=source.id, source_slug="acme", company_name="Acme", external_job_id="1", title="Engineer", normalized_title="engineer", raw_json={}, first_seen_at=now, last_seen_at=now),
            JobPosting(source_id=source.id, source_slug="acme", company_name="Acme", external_job_id="2", title="Closed", normalized_title="closed", raw_json={}, active=False, first_seen_at=now - timedelta(days=2), last_seen_at=now),
            ScrapeRun(status="completed", dry_run=False, sources_requested=["acme"], finished_at=now),
        ]
    )
    db_session.commit()
    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/health/ready").json() == {"status": "ok"}
    response = client.get("/admin/operations")
    assert response.status_code == 200
    payload = response.json()
    assert payload["sources"]["total"] == 1
    assert payload["sources"]["due"] == 1
    assert payload["sources"]["unhealthy"] == 1
    assert payload["jobs"]["active"] == 1
    assert payload["jobs"]["inactive"] == 1
    assert payload["recent_runs"][0]["status"] == "completed"
    assert "config_json" not in payload["sources"]["items"][0]


def test_operations_frontend_contract_is_served(client) -> None:
    page = client.get("/app/operations.html")
    script = client.get("/app/assets/pages/operations.js")
    navigation = client.get("/app/assets/navigation.js")
    discovery = client.get("/app/job-discovery.html")
    assert page.status_code == 200
    assert all(marker in page.text for marker in ("data-system-status", "data-source-board", "data-run-list", "data-operation-message"))
    assert script.status_code == 200
    assert "api.runDueSources" in script.text
    assert "/app/operations.html" in navigation.text
    assert all(marker in discovery.text for marker in ("data-source", "data-ats", "data-workplace", "data-pagination", "data-freshness"))
