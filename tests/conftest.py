from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from hunt_board.db import Base
from hunt_board.db.session import get_db
from hunt_board.db.models import User
from hunt_board.main import create_app
from hunt_board.auth.dependencies import optional_user, require_admin, require_user


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    with SessionLocal() as session:
        yield session


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    app = create_app()

    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    def override_user(db: Session = Depends(get_db)) -> User:
        user = db.scalar(select(User).where(User.is_active.is_(True)).order_by(User.id))
        if user is None:
            user = User(
                email="test-owner@example.com",
                normalized_email="test-owner@example.com",
                role="admin",
                is_admin=True,
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        return user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_user] = override_user
    app.dependency_overrides[require_admin] = override_user
    app.dependency_overrides[optional_user] = override_user
    with TestClient(app) as test_client:
        yield test_client
