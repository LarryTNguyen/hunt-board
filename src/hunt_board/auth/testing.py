from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from hunt_board.db.models import User


def get_test_user(db: Session, *, admin: bool = False) -> User:
    """Offline-only dependency helper. Production code never calls this."""
    user = db.scalar(select(User).where(User.is_active.is_(True)).order_by(User.id))
    if user is None:
        raise HTTPException(status_code=503, detail="Test user is not seeded")
    if admin:
        user.role = "admin"
        user.is_admin = True
    return user
