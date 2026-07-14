from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from hunt_board.db.models import ApplicationStatus, User, UserPreference
from hunt_board.ingestion.registry import SourceSyncResult, sync_sources_from_yaml
from hunt_board.matching.ranking import UserPreferences


DEFAULT_APPLICATION_STATUSES = [
    "Nothing",
    "Applied",
    "OA Received",
    "Interview Scheduled",
    "Positive Hear Back",
    "Ghosted",
    "Rejection",
    "Offer Received",
    "Withdrawn",
]


@dataclass(frozen=True)
class SeedResult:
    user_created: bool
    statuses_created: int
    sources: SourceSyncResult


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def seed_milestone_one(db: Session, email: str, sources_path: str) -> SeedResult:
    user = db.scalar(select(User).where(User.email == email))
    user_created = user is None
    defaults = UserPreferences()
    if user is None:
        user = User(email=email, is_admin=True, is_active=True, preferences_json=defaults.model_dump())
        db.add(user)
        db.flush()
    preference = db.scalar(select(UserPreference).where(UserPreference.user_id == user.id))
    if preference is None:
        preference = UserPreference(
            user_id=user.id,
            include_keywords=defaults.include_keywords,
            exclude_keywords=defaults.exclude_keywords,
            role_groups=defaults.role_groups,
            preferred_levels=defaults.preferred_levels,
            preferred_locations=defaults.preferred_locations,
            home_location=defaults.home_location,
            radius_miles=defaults.radius_miles,
            country=defaults.country,
            remote_allowed=defaults.remote_allowed,
            minimum_score_threshold=defaults.minimum_score_threshold,
        )
        db.add(preference)

    existing_statuses = set(db.scalars(select(ApplicationStatus.name)).all())
    statuses_created = 0
    terminal = {"Ghosted", "Rejection", "Offer Received", "Withdrawn"}
    for index, name in enumerate(DEFAULT_APPLICATION_STATUSES):
        if name in existing_statuses:
            continue
        db.add(
            ApplicationStatus(
                name=name,
                slug=_slugify(name),
                sort_order=index,
                is_terminal=name in terminal,
            )
        )
        statuses_created += 1
    sources = sync_sources_from_yaml(db, sources_path, commit=False)
    db.commit()
    return SeedResult(user_created=user_created, statuses_created=statuses_created, sources=sources)
