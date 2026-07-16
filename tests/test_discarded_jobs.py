from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from hunt_board.db.models import JobPosting, Notification, Source
from hunt_board.db.seed import seed_milestone_one


SOURCE_FILE = Path(__file__).parent / "fixtures" / "sources_acme.yaml"


def _seed(db_session) -> Source:
    seed_milestone_one(db_session, "owner@example.com", str(SOURCE_FILE))
    return db_session.scalar(select(Source).where(Source.slug == "acme"))


def _job(db_session, source: Source, external_id: str, title: str, *, score: float = 80) -> JobPosting:
    now = datetime.now(timezone.utc)
    job = JobPosting(
        source_id=source.id,
        source_slug=source.slug,
        company_name="Acme",
        external_job_id=external_id,
        title=title,
        normalized_title=title.lower(),
        location="Remote, United States",
        normalized_location="remote, united states",
        workplace_type="remote",
        apply_url=f"https://jobs.example.com/{external_id}",
        canonical_apply_url=f"https://jobs.example.com/{external_id}",
        description_text="Build useful things.",
        raw_json={"id": external_id},
        ranking_score=score,
        ranking_reasons=["fixture score"],
        first_seen_at=now,
        last_seen_at=now,
    )
    db_session.add(job)
    db_session.flush()
    return job


def test_discarded_jobs_are_hidden_from_discovery_and_restorable(client, db_session) -> None:
    source = _seed(db_session)
    first_job = _job(db_session, source, "1", "Backend Engineer", score=90)
    second_job = _job(db_session, source, "2", "Data Engineer", score=80)
    db_session.commit()

    first = client.post(f"/jobs/{first_job.id}/discard")
    retry = client.post(f"/jobs/{first_job.id}/discard")
    assert first.status_code == retry.status_code == 200
    assert first.json()["id"] == retry.json()["id"]
    assert first.json()["job"]["id"] == first_job.id

    visible_ids = {job["id"] for job in client.get("/jobs").json()}
    assert visible_ids == {second_job.id}
    assert client.get(f"/jobs/{first_job.id}").json()["is_discarded"] is True
    assert {job["id"] for job in client.get("/jobs", params={"discarded": True}).json()} == {first_job.id}

    pile = client.get("/discarded-jobs")
    assert pile.status_code == 200
    assert pile.json()[0]["discarded_at"]
    assert pile.json()[0]["job"]["id"] == first_job.id

    restored = client.delete(f"/jobs/{first_job.id}/discard")
    repeated_restore = client.delete(f"/jobs/{first_job.id}/discard")
    assert restored.json() == {"job_id": first_job.id, "restored": True}
    assert repeated_restore.json() == {"job_id": first_job.id, "restored": False}
    assert {job["id"] for job in client.get("/jobs").json()} == {first_job.id, second_job.id}


def test_discarded_job_notifications_are_hidden_from_the_inbox(client, db_session) -> None:
    source = _seed(db_session)
    job = _job(db_session, source, "1", "Backend Engineer")
    db_session.flush()
    db_session.add(
        Notification(
            user_id=1,
            job_posting_id=job.id,
            kind="new_match",
            dedupe_key="fixture:discarded-job",
            payload_json={},
        )
    )
    db_session.commit()

    assert len(client.get("/notifications").json()) == 1
    assert client.post(f"/jobs/{job.id}/discard").status_code == 200
    assert client.get("/notifications").json() == []
