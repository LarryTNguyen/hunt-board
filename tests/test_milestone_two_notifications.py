from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

from hunt_board.db.models import Notification
from hunt_board.db.seed import seed_milestone_one
from hunt_board.ingestion.adapters.base import NormalizedJob
from hunt_board.ingestion.service import IngestionService


SOURCE_FILE = Path(__file__).parent / "fixtures" / "sources_acme.yaml"


class FakeAdapter:
    def __init__(self, jobs: list[NormalizedJob]) -> None:
        self.jobs = jobs

    async def fetch_jobs(self, source):
        return self.jobs


def _job(description: str = "Build APIs.") -> NormalizedJob:
    return NormalizedJob(
        source_slug="acme",
        company_name="Acme",
        external_job_id="1",
        title="Backend Engineer",
        location="Remote, United States",
        department="Engineering",
        employment_type="Full-time",
        workplace_type="remote",
        apply_url="https://jobs.example.com/1",
        description_html=f"<p>{description}</p>",
        description_text=description,
        raw_json={"id": "1", "description": description},
    )


@pytest.mark.asyncio()
async def test_ingestion_notifications_dedupe_dry_run_and_inbox_workflow(client, db_session) -> None:
    seed_milestone_one(db_session, "owner@example.com", str(SOURCE_FILE))
    service = IngestionService(str(SOURCE_FILE), adapter_overrides={"acme": FakeAdapter([_job()])})

    dry_run = await service.run(db_session, ["acme"], dry_run=True)
    assert dry_run.total_new_jobs == 1
    assert db_session.scalar(select(func.count()).select_from(Notification)) == 0

    await service.run(db_session, ["acme"])
    await service.run(db_session, ["acme"])
    notifications = db_session.scalars(select(Notification)).all()
    assert len(notifications) == 1
    assert notifications[0].kind == "new_match"

    unread = client.get("/notifications", params={"unread": True})
    assert unread.status_code == 200
    assert len(unread.json()) == 1
    notification_id = unread.json()[0]["id"]
    assert client.patch(f"/notifications/{notification_id}/read").status_code == 200
    assert client.get("/notifications", params={"unread": True}).json() == []

    # Add another unread row to exercise read-all without depending on ingestion.
    db_session.add(
        Notification(
            user_id=notifications[0].user_id,
            kind="source_health",
            dedupe_key="source_health:test",
            payload_json={"message": "test"},
        )
    )
    db_session.commit()
    read_all = client.post("/notifications/read-all")
    assert read_all.status_code == 200
    assert read_all.json()["marked_read"] == 1
    assert client.get("/notifications", params={"unread": True}).json() == []


@pytest.mark.asyncio()
async def test_description_change_notifies_for_saved_job_once(client, db_session) -> None:
    seed_milestone_one(db_session, "owner@example.com", str(SOURCE_FILE))
    service = IngestionService(str(SOURCE_FILE), adapter_overrides={"acme": FakeAdapter([_job()])})
    await service.run(db_session, ["acme"])
    job_id = client.get("/jobs").json()[0]["id"]
    client.post(f"/jobs/{job_id}/save", json={})

    changed_service = IngestionService(
        str(SOURCE_FILE), adapter_overrides={"acme": FakeAdapter([_job("Build better APIs.")])}
    )
    await changed_service.run(db_session, ["acme"])
    await changed_service.run(db_session, ["acme"])

    kinds = [notification.kind for notification in db_session.scalars(select(Notification)).all()]
    assert kinds.count("new_match") == 1
    assert kinds.count("job_updated") == 1
