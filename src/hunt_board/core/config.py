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
    http_retry_jitter_seconds: float
    run_timeout_seconds: int
    stale_run_minutes: int
    scheduler_interval_seconds: int
    scheduler_run_on_startup: bool
    scheduler_enabled: bool
    environment: str
    release: str
    process_name: str
    deployment_id: str
    public_url: str
    anomaly_zero_quarantine: bool
    anomaly_volume_change_ratio: float
    anomaly_mass_change_ratio: float
    max_job_age_days: int
    supabase_url: str
    supabase_anon_key: str
    supabase_jwt_audience: str
    supabase_jwt_issuer: str


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


def validate_runtime_settings(settings: Settings) -> None:
    if settings.environment not in {"development", "test", "staging", "production"}:
        raise ValueError("HUNT_BOARD_ENVIRONMENT must be development, test, staging, or production")
    if settings.environment in {"staging", "production"}:
        unsafe_database = any(
            marker in settings.database_url.casefold()
            for marker in ("localhost", "127.0.0.1", "sqlite", "hunt_board:hunt_board@")
        )
        missing = []
        if unsafe_database:
            missing.append("a non-local DATABASE_URL")
        if not settings.supabase_url.startswith("https://"):
            missing.append("an HTTPS SUPABASE_URL")
        if not settings.supabase_anon_key:
            missing.append("SUPABASE_ANON_KEY")
        if settings.release in {"", "development", "unknown"}:
            missing.append("HUNT_BOARD_RELEASE")
        if missing:
            raise RuntimeError(
                f"Unsafe {settings.environment} configuration; provide " + ", ".join(missing)
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        database_url=os.environ.get(
            "DATABASE_URL",
            "postgresql+psycopg://hunt_board:hunt_board@localhost:55432/hunt_board",
        ),
        sources_path=Path(os.environ.get("HUNT_BOARD_SOURCES_PATH", "data/sources.yaml")),
        default_user_email=os.environ.get("HUNT_BOARD_DEFAULT_USER_EMAIL", "owner@example.com"),
        http_timeout_seconds=max(1, float(os.environ.get("HUNT_BOARD_HTTP_TIMEOUT_SECONDS", "30"))),
        source_concurrency=max(1, int(os.environ.get("HUNT_BOARD_SOURCE_CONCURRENCY", "5"))),
        http_max_retries=max(0, int(os.environ.get("HUNT_BOARD_HTTP_MAX_RETRIES", "2"))),
        http_retry_backoff_seconds=max(
            0,
            float(os.environ.get("HUNT_BOARD_HTTP_RETRY_BACKOFF_SECONDS", "0.5")),
        ),
        http_retry_jitter_seconds=max(
            0,
            float(os.environ.get("HUNT_BOARD_HTTP_RETRY_JITTER_SECONDS", "0.25")),
        ),
        run_timeout_seconds=max(60, int(os.environ.get("HUNT_BOARD_RUN_TIMEOUT_SECONDS", "3600"))),
        stale_run_minutes=max(5, int(os.environ.get("HUNT_BOARD_STALE_RUN_MINUTES", "120"))),
        scheduler_interval_seconds=max(
            10,
            int(os.environ.get("HUNT_BOARD_SCHEDULER_INTERVAL_SECONDS", "7200")),
        ),
        scheduler_run_on_startup=_environment_bool("HUNT_BOARD_SCHEDULER_RUN_ON_STARTUP", True),
        scheduler_enabled=_environment_bool("HUNT_BOARD_SCHEDULER_ENABLED", True),
        environment=os.environ.get("HUNT_BOARD_ENVIRONMENT", "development").strip().lower(),
        release=os.environ.get("HUNT_BOARD_RELEASE", "development").strip(),
        process_name=os.environ.get("HUNT_BOARD_PROCESS", "web").strip().lower(),
        deployment_id=os.environ.get("HUNT_BOARD_DEPLOYMENT_ID", "local").strip(),
        public_url=os.environ.get("HUNT_BOARD_PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/"),
        anomaly_zero_quarantine=_environment_bool("HUNT_BOARD_ANOMALY_ZERO_QUARANTINE", True),
        anomaly_volume_change_ratio=max(
            0.1, float(os.environ.get("HUNT_BOARD_ANOMALY_VOLUME_CHANGE_RATIO", "0.75"))
        ),
        anomaly_mass_change_ratio=max(
            0.1, float(os.environ.get("HUNT_BOARD_ANOMALY_MASS_CHANGE_RATIO", "0.50"))
        ),
        max_job_age_days=max(30, int(os.environ.get("HUNT_BOARD_MAX_JOB_AGE_DAYS", "365"))),
        supabase_url=os.environ.get("SUPABASE_URL", "").rstrip("/"),
        supabase_anon_key=os.environ.get("SUPABASE_ANON_KEY", ""),
        supabase_jwt_audience=os.environ.get("SUPABASE_JWT_AUDIENCE", "authenticated"),
        supabase_jwt_issuer=(
            os.environ.get("SUPABASE_JWT_ISSUER", "").strip()
            or (
                f"{os.environ.get('SUPABASE_URL', '').rstrip('/')}/auth/v1"
                if os.environ.get("SUPABASE_URL")
                else ""
            )
        ),
    )
