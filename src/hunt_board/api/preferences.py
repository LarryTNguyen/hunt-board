from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from hunt_board.api.schemas import RescoreResponse, UserPreferenceRead, UserPreferenceUpdate
from hunt_board.auth.single_user import get_single_user
from hunt_board.db.session import get_db
from hunt_board.matching.service import ensure_user_preference, preferences_from_row, rescore_jobs

router = APIRouter(prefix="/me/preferences", tags=["preferences"])


@router.get("", response_model=UserPreferenceRead)
def get_preferences(db: Session = Depends(get_db)):
    user = get_single_user(db)
    return ensure_user_preference(db, user)


@router.patch("", response_model=UserPreferenceRead)
def update_preferences(payload: UserPreferenceUpdate, db: Session = Depends(get_db)):
    user = get_single_user(db)
    preference = ensure_user_preference(db, user)
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    for field, value in changes.items():
        setattr(preference, field, value)
    db.flush()
    user.preferences_json = preferences_from_row(preference).model_dump()
    db.commit()
    db.refresh(preference)
    return preference


@router.post("/rescore", response_model=RescoreResponse)
def rescore_existing_jobs(db: Session = Depends(get_db)) -> dict:
    user = get_single_user(db)
    preference = ensure_user_preference(db, user)
    return rescore_jobs(db, user, preference)
