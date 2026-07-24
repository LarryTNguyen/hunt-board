from __future__ import annotations

from threading import Lock
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session


INGESTION_ADVISORY_LOCK_KEY = 5212157498657161554


class IngestionAlreadyRunningError(RuntimeError):
    pass


class IngestionRunLock(Protocol):
    def acquire(self, db: Session) -> bool: ...

    def release(self) -> None: ...


class PostgreSQLAdvisoryLock:
    def __init__(self, key: int = INGESTION_ADVISORY_LOCK_KEY) -> None:
        self.key = key
        self.connection: Connection | None = None

    def acquire(self, db: Session) -> bool:
        connection = db.get_bind().connect()
        acquired = bool(connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": self.key}))
        if not acquired:
            connection.close()
            return False
        self.connection = connection
        return True

    def release(self) -> None:
        if self.connection is None:
            return
        try:
            self.connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": self.key})
        finally:
            self.connection.close()
            self.connection = None


_LOCAL_LOCK = Lock()


class LocalIngestionRunLock:
    def __init__(self) -> None:
        self.acquired = False

    def acquire(self, db: Session) -> bool:
        self.acquired = _LOCAL_LOCK.acquire(blocking=False)
        return self.acquired

    def release(self) -> None:
        if self.acquired:
            self.acquired = False
            _LOCAL_LOCK.release()


def ingestion_lock_for(db: Session) -> IngestionRunLock:
    if db.get_bind().dialect.name == "postgresql":
        return PostgreSQLAdvisoryLock()
    return LocalIngestionRunLock()
