from __future__ import annotations

from datetime import datetime, timedelta, timezone

from hunt_board.db.models import (
    Application,
    ApplicationStatus,
    JobPosting,
    SavedSearch,
    Source,
    User,
    UserPreference,
)


def _seed(db_session, *, with_searches: bool = True, with_application: bool = True):
    user = User(email="owner@example.com")
    preference = UserPreference(user=user, minimum_score_threshold=60)
    source = Source(
        slug="acme",
        name="Acme",
        ats="greenhouse",
        company_name="Acme",
        config_json={"private": "must not leak"},
    )
    active_status = ApplicationStatus(
        name="Applied", slug="applied", sort_order=1, is_terminal=False
    )
    terminal_status = ApplicationStatus(
        name="Rejected", slug="rejected", sort_order=2, is_terminal=True
    )
    db_session.add_all([user, preference, source, active_status, terminal_status])
    db_session.flush()
    job = JobPosting(
        source_id=source.id,
        source_slug=source.slug,
        company_name=source.company_name,
        external_job_id="1",
        title="Backend Engineer",
        normalized_title="backend engineer",
        location="Remote",
        normalized_location="remote",
        workplace_type="remote",
        description_text="Build APIs",
        raw_json={"private": "must not leak"},
        ranking_score=95,
        first_seen_at=datetime.now(timezone.utc) - timedelta(hours=2),
        last_seen_at=datetime.now(timezone.utc),
    )
    db_session.add(job)
    db_session.flush()
    application = Application(
        user_id=user.id,
        job_posting_id=job.id,
        status_id=active_status.id,
        status=active_status.slug,
        updated_at=datetime.now(timezone.utc) - timedelta(days=8),
    )
    if with_application:
        db_session.add(application)
    if with_searches:
        db_session.add_all(
            [
                SavedSearch(
                    user_id=user.id,
                    name="Backend",
                    filters_json={"q": "backend", "application_state": "any"},
                    is_active=True,
                ),
                SavedSearch(
                    user_id=user.id,
                    name="Remote",
                    filters_json={"remote_only": True, "application_state": "any"},
                    is_active=True,
                ),
            ]
        )
    db_session.commit()
    return job


def test_daily_dashboard_aggregates_and_dedupes(client, db_session) -> None:
    job = _seed(db_session)
    response = client.get("/dashboard/daily")
    assert response.status_code == 200
    payload = response.json()
    assert "freshness" not in payload
    assert payload["totals"]["active_jobs"] == 1
    assert payload["totals"]["active_saved_searches"] == 2
    assert len(payload["saved_searches"]) == 2
    assert [item["id"] for item in payload["top_new_matches"]] == [job.id]
    assert payload["application_pipeline"][0]["count"] == 1
    assert payload["follow_up_candidates"][0]["id"] > 0
    serialized = response.text
    assert "raw_json" not in serialized
    assert "config_json" not in serialized
    assert "must not leak" not in serialized


def test_daily_dashboard_fallback_without_saved_searches(client, db_session) -> None:
    job = _seed(db_session, with_searches=False, with_application=False)
    payload = client.get("/dashboard/daily").json()
    assert payload["saved_searches"] == []
    assert [item["id"] for item in payload["top_new_matches"]] == [job.id]
    assert payload["totals"]["active_saved_searches"] == 0
