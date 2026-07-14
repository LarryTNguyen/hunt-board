from __future__ import annotations

from datetime import datetime, timezone

from hunt_board.db.models import JobPosting, ScrapeRun, Source


def test_health(client) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_database_health(client) -> None:
    response = client.get("/health/db")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_jobs_api_lists_ranked_jobs(client, db_session) -> None:
    source = Source(slug="acme", name="Acme", ats="greenhouse", company_name="Acme")
    db_session.add(source)
    db_session.flush()
    db_session.add(
        JobPosting(
            source_id=source.id,
            source_slug=source.slug,
            company_name="Acme",
            external_job_id="1",
            title="Backend Engineer",
            normalized_title="backend engineer",
            location="Remote",
            normalized_location="remote",
            raw_json={"id": "1"},
            ranking_score=91,
            ranking_reasons=["exact include title match"],
            first_seen_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()

    response = client.get("/jobs")

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["title"] == "Backend Engineer"
    assert payload[0]["ranking_score"] == 91


def test_admin_scrape_runs_api(client, db_session) -> None:
    db_session.add(ScrapeRun(status="completed", dry_run=False, sources_requested=["acme"]))
    db_session.commit()

    response = client.get("/api/admin/scrape-runs")

    assert response.status_code == 200
    assert response.json()[0]["status"] == "completed"


def test_admin_source_sync_api(client) -> None:
    response = client.post("/admin/sources/sync-from-yaml")

    assert response.status_code == 200
    assert response.json()["created"] == 3
    sources = client.get("/admin/sources")
    assert sources.status_code == 200
    assert {source["slug"] for source in sources.json()} == {"discord", "highlevel", "notion"}
