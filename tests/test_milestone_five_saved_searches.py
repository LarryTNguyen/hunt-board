from __future__ import annotations

from datetime import datetime, timedelta, timezone

from hunt_board.db.models import JobPosting, Source, User


def _seed(db_session):
    user = User(email="owner@example.com")
    source = Source(
        slug="acme",
        name="Acme",
        ats="greenhouse",
        company_name="Acme",
    )
    db_session.add_all([user, source])
    db_session.flush()
    old_job = JobPosting(
        source_id=source.id,
        source_slug=source.slug,
        company_name=source.company_name,
        external_job_id="old",
        title="Backend Engineer",
        normalized_title="backend engineer",
        location="Remote, United States",
        normalized_location="remote united states",
        location_country_code="US",
        location_country="United States",
        workplace_type="remote",
        description_text="Build APIs",
        raw_json={},
        ranking_score=92,
        first_seen_at=datetime.now(timezone.utc) - timedelta(days=2),
        last_seen_at=datetime.now(timezone.utc),
    )
    other_job = JobPosting(
        source_id=source.id,
        source_slug=source.slug,
        company_name=source.company_name,
        external_job_id="other",
        title="Product Designer",
        normalized_title="product designer",
        location="New York, United States",
        normalized_location="new york united states",
        location_country_code="US",
        location_country="United States",
        workplace_type="onsite",
        description_text="Design products",
        raw_json={},
        ranking_score=75,
        first_seen_at=datetime.now(timezone.utc) - timedelta(days=1),
        last_seen_at=datetime.now(timezone.utc),
    )
    db_session.add_all([old_job, other_job])
    db_session.commit()
    return source, old_job


def test_saved_search_crud_validation_and_default_behavior(client, db_session) -> None:
    _seed(db_session)
    first = client.post(
        "/saved-searches",
        json={
            "name": "Backend route",
            "filters": {"q": "backend", "country": "us", "remote_only": True},
            "is_default": True,
        },
    )
    assert first.status_code == 200
    first_payload = first.json()
    assert first_payload["filters"]["country"] == "US"
    assert first_payload["match_count"] == 1
    assert first_payload["new_since_review_count"] == 1

    duplicate = client.post(
        "/saved-searches",
        json={"name": "backend route", "filters": {}},
    )
    assert duplicate.status_code == 409
    assert client.post(
        "/saved-searches",
        json={"name": "Invalid", "filters": {"source_id": 1}},
    ).status_code == 422
    assert client.post(
        "/saved-searches",
        json={"name": "Invalid sort", "sort_by": "magic", "filters": {}},
    ).status_code == 422

    second = client.post(
        "/saved-searches",
        json={"name": "All roles", "filters": {}, "is_default": True},
    ).json()
    listed = client.get("/saved-searches").json()
    defaults = [item["id"] for item in listed if item["is_default"]]
    assert defaults == [second["id"]]

    updated = client.patch(
        f"/saved-searches/{first_payload['id']}",
        json={"description": "  Focused route  ", "is_active": False},
    )
    assert updated.status_code == 200
    assert updated.json()["description"] == "Focused route"
    assert client.get("/saved-searches?active=false").json()[0]["id"] == first_payload["id"]
    removed = client.delete(f"/saved-searches/{first_payload['id']}")
    assert removed.json() == {"saved_search_id": first_payload["id"], "removed": True}


def test_saved_search_review_state_and_new_only(client, db_session) -> None:
    source, old_job = _seed(db_session)
    created = client.post(
        "/saved-searches",
        json={
            "name": "Backend route",
            "filters": {"q": "backend", "application_state": "any"},
        },
    ).json()
    search_id = created["id"]
    assert client.get(f"/saved-searches/{search_id}/matches").json()["items"][0]["id"] == old_job.id

    reviewed = client.post(f"/saved-searches/{search_id}/mark-reviewed")
    assert reviewed.status_code == 200
    assert reviewed.json()["new_since_review_count"] == 0

    new_job = JobPosting(
        source_id=source.id,
        source_slug=source.slug,
        company_name=source.company_name,
        external_job_id="new",
        title="Senior Backend Engineer",
        normalized_title="senior backend engineer",
        location="Remote",
        normalized_location="remote",
        workplace_type="remote",
        description_text="Build backend systems",
        raw_json={},
        ranking_score=98,
        first_seen_at=datetime.now(timezone.utc) + timedelta(seconds=1),
        last_seen_at=datetime.now(timezone.utc),
    )
    db_session.add(new_job)
    db_session.commit()

    matches = client.get(f"/saved-searches/{search_id}/matches?new_only=true").json()
    assert matches["new_since_review_count"] == 1
    assert matches["total"] == 1
    assert [item["id"] for item in matches["items"]] == [new_job.id]
