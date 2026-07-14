from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str
    sources_path: Path
    default_user_email: str
    http_timeout_seconds: float


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        database_url=os.environ.get(
            "DATABASE_URL",
            "postgresql+psycopg://hunt_board:hunt_board@localhost:55432/hunt_board",
        ),
        sources_path=Path(os.environ.get("HUNT_BOARD_SOURCES_PATH", "data/sources.yaml")),
        default_user_email=os.environ.get("HUNT_BOARD_DEFAULT_USER_EMAIL", "owner@example.com"),
        http_timeout_seconds=float(os.environ.get("HUNT_BOARD_HTTP_TIMEOUT_SECONDS", "20")),
    )
