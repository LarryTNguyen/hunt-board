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
    source_concurrency: int
    http_max_retries: int
    http_retry_backoff_seconds: float
    stale_run_minutes: int
    scheduler_interval_seconds: int
    scheduler_run_on_startup: bool
    scheduler_enabled: bool


def _environment_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    normalized = raw.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        database_url=os.environ.get(
            "DATABASE_URL",
            "postgresql+psycopg://hunt_board:hunt_board@localhost:55432/hunt_board",
        ),
        sources_path=Path(os.environ.get("HUNT_BOARD_SOURCES_PATH", "data/sources.yaml")),
        default_user_email=os.environ.get("HUNT_BOARD_DEFAULT_USER_EMAIL", "owner@example.com"),
        http_timeout_seconds=float(os.environ.get("HUNT_BOARD_HTTP_TIMEOUT_SECONDS", "10")),
        source_concurrency=max(1, int(os.environ.get("HUNT_BOARD_SOURCE_CONCURRENCY", "5"))),
        http_max_retries=max(0, int(os.environ.get("HUNT_BOARD_HTTP_MAX_RETRIES", "2"))),
        http_retry_backoff_seconds=max(
            0,
            float(os.environ.get("HUNT_BOARD_HTTP_RETRY_BACKOFF_SECONDS", "0.5")),
        ),
        stale_run_minutes=max(5, int(os.environ.get("HUNT_BOARD_STALE_RUN_MINUTES", "120"))),
        scheduler_interval_seconds=max(
            10,
            int(os.environ.get("HUNT_BOARD_SCHEDULER_INTERVAL_SECONDS", "300")),
        ),
        scheduler_run_on_startup=_environment_bool("HUNT_BOARD_SCHEDULER_RUN_ON_STARTUP", True),
        scheduler_enabled=_environment_bool("HUNT_BOARD_SCHEDULER_ENABLED", True),
    )
