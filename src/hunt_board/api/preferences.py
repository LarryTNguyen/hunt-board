from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from hunt_board.api.schemas import OnboardingRead, OnboardingUpdate, RescoreResponse, UserPreferenceRead, UserPreferenceUpdate
from hunt_board.auth.dependencies import require_user
from hunt_board.db.models import User
from hunt_board.db.session import get_db
from hunt_board.matching.service import ensure_user_preference, preferences_from_row, rescore_jobs

router = APIRouter(prefix="/me/preferences", tags=["preferences"])
logger = logging.getLogger("hunt_board")


@router.get("", response_model=UserPreferenceRead)
def get_preferences(user: User = Depends(require_user), db: Session = Depends(get_db)):
    return ensure_user_preference(db, user)


@router.patch("", response_model=UserPreferenceRead)
def update_preferences(
    payload: UserPreferenceUpdate,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    preference = ensure_user_preference(db, user)
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    for nullable_field in ("sponsorship_required", "minimum_salary"):
        if nullable_field in payload.model_fields_set:
            changes[nullable_field] = getattr(payload, nullable_field)
    for field, value in changes.items():
        setattr(preference, field, value)
    db.flush()
    user.preferences_json = preferences_from_row(preference).model_dump(mode="json")
    db.commit()
    db.refresh(preference)
    logger.info(
        "preference.updated",
        extra={
            "event_name": "preference.updated",
            "event_data": {"user_id": user.id, "changed_fields": sorted(changes)},
        },
    )
    return preference


@router.post("/rescore", response_model=RescoreResponse)
def rescore_existing_jobs(
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    preference = ensure_user_preference(db, user)
    return rescore_jobs(db, user, preference)


@router.get("/onboarding", response_model=OnboardingRead)
def onboarding_state(user: User = Depends(require_user)) -> dict:
    state = "completed" if user.onboarding_completed_at else "skipped" if user.onboarding_skipped_at else "pending"
    return {
        "state": state,
        "completed_at": user.onboarding_completed_at,
        "skipped_at": user.onboarding_skipped_at,
        "preferences_help_relevance": state != "completed",
    }


@router.post("/onboarding", response_model=OnboardingRead)
def update_onboarding(
    payload: OnboardingUpdate,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    now = datetime.now(timezone.utc)
    if payload.action == "complete":
        user.onboarding_completed_at = now
        user.onboarding_skipped_at = None
    elif payload.action == "skip":
        user.onboarding_skipped_at = now
        user.onboarding_completed_at = None
    else:
        user.onboarding_completed_at = None
        user.onboarding_skipped_at = None
    db.commit()
    return onboarding_state(user)
