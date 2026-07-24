from __future__ import annotations

from datetime import datetime, timedelta, timezone

from hunt_board.db.models import (
    Application,
    ApplicationStatus,
    DiscardedJob,
    JobPosting,
    SavedJob,
    Source,
    User,
)


def _job(source: Source, external_id: str, title: str, **overrides) -> JobPosting:
    values = {
        "source_id": source.id,
        "source_slug": source.slug,
        "company_name": source.company_name,
        "external_job_id": external_id,
        "title": title,
        "normalized_title": title.lower(),
        "location": "Remote, United States",
        "normalized_location": "remote united states",
        "location_country_code": "US",
        "location_country": "United States",
        "department": "Engineering",
        "workplace_type": "remote",
        "description_text": "Build distributed APIs and observability systems",
        "raw_json": {},
        "ranking_score": 80,
        "posted_at": datetime.now(timezone.utc) - timedelta(days=2),
        "first_seen_at": datetime.now(timezone.utc) - timedelta(days=1),
        "last_seen_at": datetime.now(timezone.utc),
    }
    values.update(overrides)
    return JobPosting(**values)


def _seed(db_session):
    user = User(email="owner@example.com")
    greenhouse = Source(slug="acme", name="Acme", ats="greenhouse", company_name="Acme")
    lever = Source(slug="beta", name="Beta", ats="lever", company_name="Beta Labs")
    status = ApplicationStatus(name="Applied", slug="applied", sort_order=1)
    db_session.add_all([user, greenhouse, lever, status])
    db_session.flush()
    jobs = [
        _job(greenhouse, "1", "Backend Engineer", ranking_score=95, salary_min=100_000, salary_max=140_000),
        _job(greenhouse, "2", "Platform Engineer", location="Austin, United States", workplace_type="hybrid"),
        _job(lever, "3", "Product Designer", location="Toronto, Canada", normalized_location="toronto canada", location_country_code="CA", location_country="Canada", department="Design", workplace_type="onsite", description_text="Own accessible product flows", ranking_score=70),
        _job(lever, "4", "Data Engineer", description_text="Maintain rareword telemetry pipelines", ranking_score=88, posted_at=datetime.now(timezone.utc) - timedelta(days=30)),
        _job(lever, "5", "Closed Engineer", active=False),
        _job(lever, "6", "Duplicate Engineer", duplicate_status="duplicate"),
    ]
    db_session.add_all(jobs)
    db_session.flush()
    db_session.add(SavedJob(user_id=user.id, job_posting_id=jobs[0].id))
    db_session.add(DiscardedJob(user_id=user.id, job_posting_id=jobs[1].id))
    db_session.add(Application(user_id=user.id, job_posting_id=jobs[2].id, status_id=status.id, status="applied"))
    db_session.commit()
    return user, jobs


def test_feed_defaults_total_and_deterministic_pagination(client, db_session) -> None:
    _, jobs = _seed(db_session)
    first = client.get("/jobs/feed?limit=1&sort_by=ranking_score&sort_order=desc").json()
    second = client.get("/jobs/feed?limit=1&offset=1&sort_by=ranking_score&sort_order=desc").json()
    assert first["total"] == 2
    assert first["has_more"] is True
    assert first["limit"] == 1
    assert {first["items"][0]["id"], second["items"][0]["id"]} == {jobs[0].id, jobs[3].id}
    assert first["items"][0]["id"] != second["items"][0]["id"]


def test_feed_structured_filters_application_state_and_posted_age(client, db_session) -> None:
    _, jobs = _seed(db_session)
    assert client.get("/jobs/feed?company=Acme&application_state=any").json()["total"] == 1
    assert client.get("/jobs/feed?source_slug=beta&application_state=any").json()["total"] == 2
    assert client.get("/jobs/feed?ats=greenhouse&application_state=any").json()["total"] == 1
    assert client.get("/jobs/feed?location=Toronto&application_state=any").json()["items"][0]["id"] == jobs[2].id
    assert client.get("/jobs/feed?country=CA&application_state=any").json()["items"][0]["id"] == jobs[2].id
    assert client.get("/jobs/feed?workplace_type=onsite&application_state=any").json()["total"] == 1
    assert client.get("/jobs/feed?salary_known=true&application_state=any").json()["items"][0]["id"] == jobs[0].id
    assert client.get("/jobs/feed?saved=true&application_state=any").json()["items"][0]["id"] == jobs[0].id
    assert client.get("/jobs/feed?discarded=true&application_state=any").json()["items"][0]["id"] == jobs[1].id
    assert client.get("/jobs/feed?application_state=tracked").json()["items"][0]["id"] == jobs[2].id
    assert client.get("/jobs/feed?application_status=applied&application_state=any").json()["items"][0]["id"] == jobs[2].id
    assert client.get("/jobs/feed?remote_only=true&application_state=any").json()["total"] == 2
    assert client.get("/jobs/feed?min_score=90&application_state=any").json()["items"][0]["id"] == jobs[0].id
    assert client.get("/jobs/feed?posted_within_days=7&application_state=any").json()["total"] == 2


def test_feed_search_fallback_relevance_and_self_excluding_facets(client, db_session) -> None:
    _, jobs = _seed(db_session)
    description = client.get("/jobs/feed?q=rareword&application_state=any&sort_by=relevance").json()
    assert [item["id"] for item in description["items"]] == [jobs[3].id]
    title = client.get("/jobs/feed?q=Engineer&application_state=any&sort_by=relevance").json()
    assert title["items"][0]["title"] in {"Backend Engineer", "Data Engineer"}
    country = client.get("/jobs/feed?country=US&application_state=any").json()
    assert {facet["value"] for facet in country["facets"]["countries"]} == {"US", "CA"}
    ats = client.get("/jobs/feed?ats=greenhouse&application_state=any").json()
    assert {facet["value"] for facet in ats["facets"]["ats"]} == {"greenhouse", "lever"}


def test_legacy_jobs_list_contract_remains_a_list(client, db_session) -> None:
    _seed(db_session)
    response = client.get("/jobs?search=rareword")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
    assert response.json()[0]["title"] == "Data Engineer"
