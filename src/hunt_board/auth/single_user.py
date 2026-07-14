from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from hunt_board.db.models import User


def get_single_user(db: Session, *, required: bool = True) -> User | None:
    """Return the active single-user MVP account in a deterministic way."""
    user = db.scalar(select(User).where(User.is_active.is_(True)).order_by(User.id))
    if user is None and required:
        raise HTTPException(
            status_code=503,
            detail="Default user is not seeded; run `uv run hunt-board seed`.",
        )
    return user
