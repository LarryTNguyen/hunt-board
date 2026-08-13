from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from hunt_board.db.models import DuplicateReview, JobPosting, Source
from hunt_board.db.seed import seed_milestone_one


SOURCE_FILE = Path(__file__).parent / "fixtures" / "sources_acme.yaml"


def _seed(db_session) -> Source:
    seed_milestone_one(db_session, "owner@example.com", str(SOURCE_FILE))
    return db_session.scalar(select(Source).where(Source.slug == "acme"))


def _job(
    db_session,
    source: Source,
    external_id: str,
    title: str,
    *,
    company: str = "Acme",
    location: str = "Remote, United States",
    score: float = 80,
    active: bool = True,
    duplicate_status: str = "unique",
    country_code: str | None = "US",
    country_name: str | None = "United States",
    salary_min: Decimal | None = None,
    salary_max: Decimal | None = None,
) -> JobPosting:
    now = datetime.now(timezone.utc)
    job = JobPosting(
        source_id=source.id,
        source_slug=source.slug,
        company_name=company,
        external_job_id=external_id,
        title=title,
        normalized_title=title.lower(),
        location=location,
        normalized_location=location.lower(),
        location_country_code=country_code,
        location_country=country_name,
        workplace_type="remote" if "remote" in location.lower() else "onsite",
        salary_min=salary_min,
        salary_max=salary_max,
        salary_currency="USD" if salary_min is not None or salary_max is not None else None,
        salary_interval="year" if salary_min is not None or salary_max is not None else None,
        apply_url=f"https://jobs.example.com/{external_id}",
        canonical_apply_url=f"https://jobs.example.com/{external_id}",
        description_text="Build useful things.",
        raw_json={"id": external_id},
        ranking_score=score,
        ranking_reasons=["fixture score"],
        active=active,
        duplicate_status=duplicate_status,
        first_seen_at=now,
        last_seen_at=now,
    )
    db_session.add(job)
    db_session.flush()
    return job


def test_rich_job_browsing_filters_sorts_paginates_and_enriches(client, db_session) -> None:
    source = _seed(db_session)
    top = _job(db_session, source, "1", "Backend Engineer", score=95, salary_min=Decimal("120000"), salary_max=Decimal("160000"))
    _job(db_session, source, "2", "Data Analyst", company="Beta", location="Toronto", score=70, country_code="CA", country_name="Canada")
    _job(db_session, source, "3", "Duplicate Backend Engineer", score=99, duplicate_status="duplicate")
    _job(db_session, source, "4", "Closed Engineer", score=90, active=False)
    db_session.commit()

    assert client.post(f"/jobs/{top.id}/save", json={"notes": "Review"}).status_code == 200
    assert client.post(f"/jobs/{top.id}/applications", json={}).status_code == 200

    default_jobs = client.get("/jobs").json()
    assert [job["title"] for job in default_jobs] == ["Backend Engineer", "Data Analyst"]
    assert default_jobs[0]["is_saved"] is True
    assert default_jobs[0]["has_application"] is True
    assert default_jobs[0]["application_status"]["slug"] == "applied"
    assert default_jobs[0]["source"]["ats"] == "greenhouse"
    assert default_jobs[0]["company_logo_url"] == "https://example.com/acme-logo.svg"
    assert default_jobs[0]["location_country_code"] == "US"
    assert default_jobs[0]["location_country"] == "United States"
    assert default_jobs[0]["salary_min"] == 120000
    assert default_jobs[0]["salary_max"] == 160000
    assert default_jobs[0]["salary_currency"] == "USD"
    assert default_jobs[0]["salary_interval"] == "year"

    assert len(client.get("/jobs", params={"include_duplicates": True}).json()) == 3
    assert len(client.get("/jobs", params={"active": False}).json()) == 1
    assert client.get("/jobs", params={"title": "analyst"}).json()[0]["company_name"] == "Beta"
    assert client.get("/jobs", params={"company": "bet"}).json()[0]["title"] == "Data Analyst"
    assert client.get("/jobs", params={"location": "toronto"}).json()[0]["title"] == "Data Analyst"
    assert client.get("/jobs", params={"country": "CA"}).json()[0]["title"] == "Data Analyst"
    assert client.get("/jobs", params={"country": "United States"}).json()[0]["title"] == "Backend Engineer"
    assert client.get("/jobs", params={"salary_known": True}).json()[0]["title"] == "Backend Engineer"
    assert client.get("/jobs", params={"source_slug": "acme"}).status_code == 200
    assert client.get("/jobs", params={"ats": "greenhouse"}).status_code == 200
    assert len(client.get("/jobs", params={"remote_only": True}).json()) == 1
    assert len(client.get("/jobs", params={"saved": True}).json()) == 1
    assert len(client.get("/jobs", params={"application_status": "applied"}).json()) == 1
    assert client.get("/jobs", params={"limit": 1, "offset": 1}).json()[0]["title"] == "Data Analyst"
    ascending = client.get("/jobs", params={"sort_by": "ranking_score", "sort_order": "asc"}).json()
    assert [job["ranking_score"] for job in ascending] == [70, 95]

    detail = client.get(f"/jobs/{top.id}").json()
    assert detail["saved_job_id"] is not None
    assert detail["application_id"] is not None
    assert detail["description_text"] == "Build useful things."


def test_preferences_update_validation_and_rescore(client, db_session) -> None:
    source = _seed(db_session)
    target = _job(db_session, source, "1", "Data Scientist", score=0)
    db_session.commit()

    current = client.get("/me/preferences")
    assert current.status_code == 200
    assert current.json()["minimum_score_threshold"] == 60

    invalid_group = client.patch("/me/preferences", json={"role_groups": ["made_up"]})
    invalid_threshold = client.patch("/me/preferences", json={"minimum_score_threshold": 101})
    invalid_empty = client.patch("/me/preferences", json={"include_keywords": [""]})
    assert invalid_group.status_code == 422
    assert invalid_threshold.status_code == 422
    assert invalid_empty.status_code == 422

    updated = client.patch(
        "/me/preferences",
        json={
            "include_keywords": [" Data Scientist ", "data scientist"],
            "exclude_keywords": [],
            "role_groups": [],
            "minimum_score_threshold": 50,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["include_keywords"] == ["Data Scientist"]
    db_session.refresh(target)
    assert target.ranking_score == 0

    response = client.post("/me/preferences/rescore")
    assert response.status_code == 200
    assert response.json()["total_jobs_rescored"] == 1
    assert response.json()["total_visible_jobs"] == 1
    db_session.refresh(target)
    assert target.ranking_score >= 50


def test_saved_job_workflow_is_idempotent_and_updates_job_state(client, db_session) -> None:
    source = _seed(db_session)
    job = _job(db_session, source, "1", "Backend Engineer")
    db_session.commit()

    first = client.post(f"/jobs/{job.id}/save", json={"notes": "First note"})
    second = client.post(f"/jobs/{job.id}/save", json={"notes": "Ignored idempotent retry"})
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert second.json()["notes"] == "First note"

    changed = client.patch(f"/saved-jobs/{first.json()['id']}", json={"notes": "Updated note"})
    assert changed.status_code == 200
    assert changed.json()["notes"] == "Updated note"
    saved_payload = client.get("/saved-jobs").json()[0]["job"]
    assert saved_payload["id"] == job.id
    assert saved_payload["source_slug"] == "acme"
    assert client.get(f"/jobs/{job.id}").json()["is_saved"] is True

    removed = client.delete(f"/jobs/{job.id}/save")
    missing = client.delete(f"/jobs/{job.id}/save")
    assert removed.json()["removed"] is True
    assert missing.json()["removed"] is False
    assert client.get(f"/jobs/{job.id}").json()["is_saved"] is False


def test_saved_jobs_filter_sort_and_paginate(client, db_session) -> None:
    source = _seed(db_session)
    jobs = [
        _job(
            db_session,
            source,
            str(index),
            f"Platform Engineer {index}",
            company="Beta Labs" if index >= 10 else "Acme",
            location="Seattle, WA" if index % 2 == 0 else "Remote, United States",
            score=60 + index,
        )
        for index in range(12)
    ]
    db_session.commit()
    for job in jobs:
        assert client.post(f"/jobs/{job.id}/save", json={}).status_code == 200

    first_page = client.get("/saved-jobs", params={"limit": 9}).json()
    second_page = client.get("/saved-jobs", params={"limit": 9, "offset": 9}).json()
    assert len(first_page) == 9
    assert len(second_page) == 3
    assert {item["id"] for item in first_page}.isdisjoint({item["id"] for item in second_page})

    company_matches = client.get("/saved-jobs", params={"company": "beta"}).json()
    location_matches = client.get("/saved-jobs", params={"location": "Seattle"}).json()
    keyword_matches = client.get("/saved-jobs", params={"q": "Engineer 3"}).json()
    score_sorted = client.get("/saved-jobs", params={"sort": "score"}).json()
    assert len(company_matches) == 2
    assert all(item["job"]["company_name"] == "Beta Labs" for item in company_matches)
    assert len(location_matches) == 6
    assert [item["job"]["title"] for item in keyword_matches] == ["Platform Engineer 3"]
    assert score_sorted[0]["job"]["ranking_score"] == 71


def test_application_tracker_status_events_and_filters(client, db_session) -> None:
    source = _seed(db_session)
    job = _job(db_session, source, "1", "Backend Engineer")
    db_session.commit()

    statuses = client.get("/application-statuses")
    assert statuses.status_code == 200
    assert "applied" in {status["slug"] for status in statuses.json()}

    first = client.post(f"/jobs/{job.id}/applications", json={"notes": "Submitted"})
    retry = client.post(f"/jobs/{job.id}/applications", json={})
    assert first.status_code == retry.status_code == 200
    assert first.json()["id"] == retry.json()["id"]
    application_id = first.json()["id"]
    assert first.json()["status"]["slug"] == "applied"
    assert len(first.json()["events"]) == 1

    assert len(client.get("/applications", params={"status": "applied"}).json()) == 1
    updated = client.patch(
        f"/applications/{application_id}",
        json={"status": "oa-received", "notes": "Assessment due", "status_note": "Email received"},
    )
    assert updated.status_code == 200
    assert updated.json()["status"]["slug"] == "oa-received"
    assert updated.json()["notes"] == "Assessment due"
    assert updated.json()["events"][-1]["old_status"] == "applied"
    assert updated.json()["events"][-1]["new_status"] == "oa-received"

    manual = client.post(
        f"/applications/{application_id}/events",
        json={"event_type": "online_assessment", "notes": "Completed"},
    )
    assert manual.status_code == 200
    events = client.get(f"/applications/{application_id}/events").json()
    assert [event["event_type"] for event in events] == [
        "status_changed",
        "status_changed",
        "online_assessment",
    ]
    detail = client.get(f"/applications/{application_id}").json()
    assert detail["job"]["id"] == job.id
    assert detail["source"]["slug"] == "acme"
    assert client.get(f"/jobs/{job.id}").json()["application_status"]["slug"] == "oa-received"

    removed = client.delete(f"/applications/{application_id}")
    assert removed.status_code == 200
    assert removed.json() == {"application_id": application_id, "job_id": job.id, "removed": True}
    assert client.get(f"/jobs/{job.id}").json()["has_application"] is False
    assert client.get(f"/applications/{application_id}/events").status_code == 404


def test_duplicate_reviews_are_self_contained_and_resolution_controls_visibility(client, db_session) -> None:
    source = _seed(db_session)
    canonical = _job(db_session, source, "1", "Backend Engineer", score=90)
    merged_candidate = _job(
        db_session, source, "2", "Backend Engineer", score=80, duplicate_status="possible_duplicate"
    )
    unique_candidate = _job(
        db_session, source, "3", "Backend Engineer II", score=70, duplicate_status="possible_duplicate"
    )
    dismissed_candidate = _job(
        db_session, source, "4", "Backend Engineer III", score=60, duplicate_status="possible_duplicate"
    )
    reviews = []
    for candidate in (merged_candidate, unique_candidate, dismissed_candidate):
        review = DuplicateReview(
            candidate_job_id=candidate.id,
            existing_job_id=canonical.id,
            reason="similar fixture",
            signals_json={"title": True},
        )
        db_session.add(review)
        reviews.append(review)
    db_session.commit()

    listed = client.get("/admin/duplicates").json()
    assert listed[0]["candidate_job"]["title"]
    assert listed[0]["existing_job"]["id"] == canonical.id

    merged = client.patch(f"/admin/duplicates/{reviews[0].id}", json={"status": "merged"})
    assert merged.status_code == 200
    visible_ids = {job["id"] for job in client.get("/jobs").json()}
    assert merged_candidate.id not in visible_ids
    assert merged_candidate.id in {
        job["id"] for job in client.get("/jobs", params={"include_duplicates": True}).json()
    }

    not_duplicate = client.patch(
        f"/admin/duplicates/{reviews[1].id}", json={"status": "not_duplicate"}
    )
    assert not_duplicate.json()["candidate_job"]["duplicate_status"] == "unique"
    assert unique_candidate.id in {job["id"] for job in client.get("/jobs").json()}

    before = dismissed_candidate.duplicate_status
    dismissed = client.patch(f"/admin/duplicates/{reviews[2].id}", json={"status": "dismissed"})
    assert dismissed.status_code == 200
    db_session.refresh(dismissed_candidate)
    assert dismissed_candidate.duplicate_status == before
