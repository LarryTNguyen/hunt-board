from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from hunt_board.db.models import ApplicationStatus, Invitation, SavedSearch, User, UserPreference
from hunt_board.ingestion.registry import SourceSyncResult, sync_sources_from_yaml
from hunt_board.matching.ranking import UserPreferences
from hunt_board.auth.security import normalize_email


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
    saved_search_created: bool = False


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def seed_milestone_one(
    db: Session,
    email: str,
    sources_path: str,
    *,
    environment: str = "development",
) -> SeedResult:
    normalized_email = normalize_email(email)
    user = db.scalar(
        select(User).where(
            (User.normalized_email == normalized_email) | (User.email == normalized_email)
        )
    )
    user_created = user is None
    defaults = UserPreferences()
    if user is None:
        if environment in {"production", "prod"}:
            raise RuntimeError("Automatic admin seeding is disabled in production")
        user = User(
            auth_user_id=uuid5(NAMESPACE_URL, f"hunt-board:local-seed:{normalized_email}"),
            email=normalized_email,
            normalized_email=normalized_email,
            role="admin",
            account_status="active",
            is_admin=True,
            is_active=True,
            preferences_json=defaults.model_dump(),
        )
        db.add(user)
        db.flush()
    else:
        user.normalized_email = normalized_email
        if user.auth_user_id is None:
            user.auth_user_id = uuid5(
                NAMESPACE_URL,
                f"hunt-board:local-seed:{normalized_email}",
            )
        if environment not in {"production", "prod"} and user.is_admin:
            user.role = "admin"
        user.account_status = "active" if user.is_active else "deactivated"
    invitation = db.scalar(
        select(Invitation).where(
            Invitation.normalized_email == normalized_email,
            Invitation.status == "accepted",
        )
    )
    if invitation is None and environment not in {"production", "prod"}:
        invitation = Invitation(
            normalized_email=normalized_email,
            inviter_user_id=user.id,
            status="accepted",
            accepted_auth_user_id=user.auth_user_id,
        )
        db.add(invitation)
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
        db.flush()

    saved_search = db.scalar(
        select(SavedSearch).where(SavedSearch.user_id == user.id).limit(1)
    )
    saved_search_created = saved_search is None
    if saved_search is None:
        db.add(
            SavedSearch(
                user_id=user.id,
                name="Daily Hunt",
                description="Default route for new active jobs above your preference threshold.",
                filters_json={
                    "active": True,
                    "discarded": False,
                    "application_state": "none",
                    "include_duplicates": False,
                    "min_score": preference.minimum_score_threshold,
                },
                sort_by="ranking_score",
                sort_order="desc",
                is_default=True,
                is_active=True,
                notify_on_new_matches=False,
            )
        )

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
    return SeedResult(
        user_created=user_created,
        statuses_created=statuses_created,
        sources=sources,
        saved_search_created=saved_search_created,
    )
