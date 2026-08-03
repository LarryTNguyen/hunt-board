from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from hunt_board.db.models import (
    Application,
    ApplicationStatus,
    JobFamily,
    JobPosting,
    ManualJob,
    Source,
    User,
)
from hunt_board.db.seed import seed_milestone_one
from hunt_board.jobs.classification import JOB_FAMILIES, apply_classification, classify_job
from hunt_board.jobs.query import JobQueryFilters, apply_job_filters, job_row_statement
from hunt_board.jobs.relaxation import execute_with_relaxation
from hunt_board.searches.schemas import SavedSearchFilters
from hunt_board.searches.service import to_job_filters
from hunt_board.core.observability import MetricsRegistry, sanitized


SOURCE_FILE = Path(__file__).parent / "fixtures" / "sources_acme.yaml"


def setup(db):
    seed_milestone_one(db, "test-owner@example.com", str(SOURCE_FILE))
    user = db.scalar(select(User).where(User.email == "test-owner@example.com"))
    source = db.scalar(select(Source).where(Source.slug == "acme"))
    return user, source


def job(db, source, external_id, title, *, family="other", company="Acme", salary=None, employment="Full-time", description=""):
    posting = JobPosting(
        source_id=source.id,
        source_slug=source.slug,
        company_name=company,
        external_job_id=external_id,
        title=title,
        normalized_title=title.casefold(),
        location="Remote, United States",
        normalized_location="remote united states",
        location_country_code="US",
        location_country="United States",
        locations_json=[{"display": "Remote, United States", "country_code": "US", "country": "United States", "is_primary": True}],
        employment_type=employment,
        workplace_type="Remote",
        salary_min=salary,
        salary_max=salary,
        job_family_slug=family,
        description_text=description,
        raw_json={},
        ranking_reasons=[],
        ranking_score=70,
    )
    db.add(posting)
    db.flush()
    return posting


@pytest.mark.parametrize(
    ("title", "family"),
    [
        ("Software Engineer", "software-engineering"),
        ("Data Analyst", "data-analytics"),
        ("Product Manager", "product-management"),
        ("Product Designer", "design-user-experience"),
        ("Senior Accountant", "finance-accounting"),
        ("Strategy Consultant", "consulting-strategy"),
        ("Growth Marketing Manager", "marketing-communications"),
        ("Account Executive", "sales-business-development"),
        ("Supply Chain Analyst", "operations-supply-chain"),
        ("Talent Acquisition Partner", "human-resources-recruiting"),
        ("Compliance Counsel", "legal-compliance"),
        ("Research Scientist", "research"),
        ("Chief of Staff", "other"),
    ],
)
def test_fixed_taxonomy_and_all_title_classifier_families(title, family) -> None:
    result = classify_job(department=None, title=title)
    assert result.family_slug == family
    assert result == classify_job(department=None, title=title)


def test_taxonomy_seed_source_precedence_description_fallback_and_override(db_session) -> None:
    setup(db_session)
    assert [(item.slug, item.name) for item in db_session.scalars(select(JobFamily).order_by(JobFamily.sort_order))] == list(JOB_FAMILIES)
    assert classify_job(department="Finance", title="Software Engineer").family_slug == "finance-accounting"
    description = classify_job(department=None, title="Associate", description="Own product roadmap and user stories")
    assert description.family_slug == "product-management"
    posting = type("Posting", (), {"classification_overridden_at": datetime.now(timezone.utc), "job_family_slug": "legal-compliance"})()
    assert apply_classification(posting, classify_job(department="Engineering", title="Engineer")) is False
    assert posting.job_family_slug == "legal-compliance"


def test_generalized_preferences_onboarding_and_immediate_feed(client, db_session) -> None:
    _, source = setup(db_session)
    finance = job(db_session, source, "fin", "Financial Analyst", family="finance-accounting")
    job(db_session, source, "eng", "Software Engineer", family="software-engineering")
    db_session.commit()
    assert client.post("/me/preferences/onboarding", json={"action": "skip"}).json()["state"] == "skipped"
    broad = client.get("/jobs/feed", params={"application_state": "any"}).json()
    assert broad["total"] == 2
    updated = client.patch(
        "/me/preferences",
        json={
            "selected_job_families": ["finance-accounting"],
            "include_keywords": [],
            "exclude_keywords": [],
            "role_groups": [],
            "desired_titles": [],
            "minimum_score_threshold": 0,
        },
    )
    assert updated.status_code == 200
    personalized = client.get("/jobs/feed", params={"application_state": "any", "use_preferences": True}).json()
    assert [item["id"] for item in personalized["items"]] == [finance.id]
    assert client.post("/me/preferences/onboarding", json={"action": "complete"}).json()["state"] == "completed"


def test_saved_search_conversion_reuses_generalized_canonical_filters() -> None:
    saved = SavedSearchFilters(
        job_families=["finance-accounting"],
        related_job_families=["consulting-strategy"],
        desired_titles=["analyst"],
        exclude_keywords=["commission"],
        excluded_companies=["Bad Co"],
        employment_types=["full-time"],
        min_salary=90_000,
    )
    canonical = to_job_filters(saved)
    assert canonical.job_families == ("finance-accounting",)
    assert canonical.related_job_families == ("consulting-strategy",)
    assert canonical.min_salary == 90_000
    with pytest.raises(ValueError):
        SavedSearchFilters.model_validate({"source_id": 123})


def test_relaxation_is_ordered_and_never_drops_exclusions_or_employment(db_session) -> None:
    user, source = setup(db_session)
    allowed = job(db_session, source, "a", "Financial Analyst", family="finance-accounting", salary=70_000)
    job(db_session, source, "b", "Financial Analyst", family="finance-accounting", salary=120_000, company="Blocked Co")
    job(db_session, source, "c", "Financial Analyst", family="finance-accounting", salary=120_000, employment="Contract")
    db_session.commit()
    filters = JobQueryFilters(
        active=True,
        application_state="any",
        discarded=None,
        job_families=("finance-accounting",),
        desired_titles=("financial analyst",),
        min_salary=100_000,
        excluded_companies=("Blocked Co",),
        employment_types=("Full-time",),
    )
    execution = execute_with_relaxation(db_session, user.id, filters, minimum_results=1)
    assert execution.strict_total == 0
    assert execution.relaxed_filters == ("min_salary",)
    ids = set(db_session.scalars(execution.final_statement.with_only_columns(JobPosting.id).order_by(None)))
    assert ids == {allowed.id}


def test_unknown_salary_multi_location_and_remote_scope_contract(client, db_session) -> None:
    _, source = setup(db_session)
    unknown = job(db_session, source, "unknown", "Operations Analyst", family="operations-supply-chain")
    unknown.salary_min = unknown.salary_max = None
    unknown.locations_json = [
        {"display": "Toronto, Canada", "country_code": "CA", "country": "Canada", "is_primary": True},
        {"display": "New York, United States", "country_code": "US", "country": "United States", "is_primary": False},
    ]
    unknown.remote_scope = "country_restricted"
    db_session.commit()
    payload = client.get("/jobs/feed", params={"countries": "US", "min_salary": 100_000, "application_state": "any"}).json()
    assert payload["items"][0]["id"] == unknown.id
    assert len(payload["items"][0]["locations"]) == 2
    assert payload["items"][0]["remote_scope"] == "country_restricted"


def test_manual_job_custom_stage_soft_delete_restore_and_permanent_delete(client, db_session) -> None:
    setup(db_session)
    custom = client.post("/application-statuses", json={"name": "Case Study", "standard_category": "interview"})
    assert custom.status_code == 200
    assert custom.json()["standard_category"] == "interview"
    created = client.post(
        "/manual-jobs",
        json={
            "company_name": "Private Advisory",
            "title": "Strategy Associate",
            "job_family_slug": "consulting-strategy",
            "application_status": custom.json()["slug"],
            "application_link": "https://example.com/follow-up",
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert body["job"] is None and body["manual_job"]["approval_status"] == "private"
    assert body["status"]["standard_category"] == "interview"
    application_id = body["id"]
    assert client.delete(f"/applications/{application_id}").status_code == 200
    deleted = client.get("/applications", params={"recently_deleted": True}).json()
    assert deleted[0]["purge_after"] is not None
    assert client.post(f"/applications/{application_id}/restore").json()["restored"] is True
    client.delete(f"/applications/{application_id}")
    assert client.delete(f"/applications/{application_id}/permanent").status_code == 200
    assert db_session.scalar(select(Application).where(Application.id == application_id)) is None
    assert db_session.scalar(select(ManualJob)) is not None


def test_public_catalog_is_limited_and_privacy_safe(client, db_session) -> None:
    _, source = setup(db_session)
    for index in range(55):
        posting = job(db_session, source, str(index), f"Role {index}")
        posting.raw_json = {"secret": "source payload"}
        posting.ranking_reasons = ["internal reason"]
    db_session.commit()
    response = client.get("/public/jobs?limit=50")
    assert response.status_code == 200
    assert len(response.json()) == 50
    forbidden = {"raw_json", "ranking_score", "ranking_reasons", "description_text", "source_id", "is_saved"}
    assert not forbidden.intersection(response.json()[0])


def test_recently_deleted_has_thirty_day_boundary(db_session) -> None:
    user, source = setup(db_session)
    posting = job(db_session, source, "delete", "Research Associate", family="research")
    status = db_session.scalar(select(ApplicationStatus).where(ApplicationStatus.slug == "applied"))
    application = Application(
        user_id=user.id,
        job_posting_id=posting.id,
        status_id=status.id,
        status=status.slug,
        deleted_at=datetime.now(timezone.utc),
        purge_after=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db_session.add(application)
    db_session.commit()
    assert timedelta(days=29) < application.purge_after - application.deleted_at <= timedelta(days=30, seconds=1)


def test_observability_redacts_search_and_uses_only_bounded_labels() -> None:
    payload = sanitized(
        {
            "query": "private search",
            "exclude_keywords": ["secret"],
            "location": "Home city",
            "company_name": "Private Company",
            "link_url": "https://private.example",
            "mode": "relaxed",
        }
    )
    assert payload["query"] == payload["location"] == payload["company_name"] == "[REDACTED]"
    registry = MetricsRegistry()
    registry.observe_search("relaxed", 0.05, 12)
    registry.observe_relaxation("min_salary")
    rendered = registry.render(active_profiles=1, deactivated_profiles=0, invitations={})
    assert 'kind="relaxed"' in rendered
    assert 'step="min_salary"' in rendered
    assert "private" not in rendered.casefold()


def test_migration_adds_rls_for_new_private_manual_domain() -> None:
    migration = (Path(__file__).parents[1] / "alembic" / "versions" / "202607310013_milestone_six_point_one.py").read_text(encoding="utf-8")
    assert 'ALTER TABLE "manual_jobs" ENABLE ROW LEVEL SECURITY' in migration
    assert '("SELECT", "select")' in migration
    assert "CREATE POLICY manual_jobs_owner_{suffix}" in migration
    assert "application_statuses_visible" in migration
