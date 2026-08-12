from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select

from hunt_board.db.models import ApplicationStatus, SavedSearch, Source, User, UserPreference
from hunt_board.db.seed import seed_milestone_one


SOURCE_FILE = Path(__file__).parent / "fixtures" / "sources_acme.yaml"


def test_seed_is_idempotent(db_session) -> None:
    first = seed_milestone_one(db_session, "owner@example.com", str(SOURCE_FILE))
    second = seed_milestone_one(db_session, "owner@example.com", str(SOURCE_FILE))

    assert first.user_created is True
    assert second.user_created is False
    assert db_session.scalar(select(func.count()).select_from(User)) == 1
    assert db_session.scalar(select(func.count()).select_from(UserPreference)) == 1
    assert db_session.scalar(select(func.count()).select_from(ApplicationStatus)) == 9
    assert db_session.scalar(select(func.count()).select_from(Source)) == 1
    assert db_session.scalar(select(func.count()).select_from(SavedSearch)) == 1
