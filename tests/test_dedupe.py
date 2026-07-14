from __future__ import annotations

from hunt_board.db.models import JobPosting, Source
from hunt_board.ingestion.adapters.base import NormalizedJob
from hunt_board.jobs.dedupe import canonicalize_url, decide_dedupe, normalize_text


def _job(external_id: str = "1", title: str = "Backend Engineer", url: str = "https://jobs.example.com/1") -> NormalizedJob:
    return NormalizedJob(
        source_slug="acme",
        company_name="Acme",
        external_job_id=external_id,
        title=title,
        location="Remote",
        department="Engineering",
        employment_type="Full-time",
        workplace_type="remote",
        apply_url=url,
        description_html=None,
        description_text=None,
        raw_json={"id": external_id},
    )


def test_canonicalize_url_removes_tracking_params() -> None:
    assert canonicalize_url("https://Jobs.Example.com/1/?utm_source=x&foo=bar") == "https://jobs.example.com/1?foo=bar"


def test_decide_dedupe_matches_source_external_id(db_session) -> None:
    source = Source(slug="acme", name="Acme", ats="greenhouse", company_name="Acme")
    db_session.add(source)
    db_session.flush()
    existing = JobPosting(
        source_id=source.id,
        source_slug=source.slug,
        company_name="Acme",
        external_job_id="1",
        title="Backend Engineer",
        normalized_title=normalize_text("Backend Engineer") or "",
        location="Remote",
        normalized_location=normalize_text("Remote"),
        canonical_apply_url="https://jobs.example.com/1",
        raw_json={"id": "1"},
        active=False,
    )
    db_session.add(existing)
    db_session.flush()

    decision = decide_dedupe(db_session, source, _job())

    assert decision.action == "upsert"
    assert decision.existing_job == existing
    assert decision.reactivated is True


def test_decide_dedupe_flags_same_company_title_location(db_session) -> None:
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
            normalized_title=normalize_text("Backend Engineer") or "",
            location="Remote",
            normalized_location=normalize_text("Remote"),
            raw_json={"id": "1"},
        )
    )
    db_session.flush()

    decision = decide_dedupe(db_session, source, _job(external_id="2", url="https://jobs.example.com/2"))

    assert decision.action == "possible_duplicate"


def test_decide_dedupe_matches_canonical_apply_url(db_session) -> None:
    source = Source(slug="acme", name="Acme", ats="greenhouse", company_name="Acme")
    db_session.add(source)
    db_session.flush()
    existing = JobPosting(
        source_id=source.id,
        source_slug=source.slug,
        company_name="Acme",
        external_job_id="1",
        title="Backend Engineer",
        normalized_title="backend engineer",
        location="Remote",
        normalized_location="remote",
        canonical_apply_url="https://jobs.example.com/1",
        raw_json={"id": "1"},
    )
    db_session.add(existing)
    db_session.flush()

    decision = decide_dedupe(
        db_session,
        source,
        _job(external_id="different", url="https://jobs.example.com/1?utm_source=test"),
    )

    assert decision.action == "upsert"
    assert decision.existing_job == existing
    assert decision.reason == "same canonical apply_url"
