from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from hunt_board.admin.api import router as admin_router
from hunt_board.admin.metrics import router as metrics_router
from hunt_board.api.schemas import IngestionHealthRead
from hunt_board.api.ingest import router as ingest_router
from hunt_board.api.jobs import public_router, router as jobs_router
from hunt_board.api.preferences import router as preferences_router
from hunt_board.db.session import get_db
from hunt_board.db.models import (
    IngestionQuarantine,
    JobLifecycleEvent,
    JobPosting,
    SavedSearch,
    ScrapeRun,
    Source,
)
from hunt_board.core.config import get_settings, validate_runtime_settings
from hunt_board.core.observability import (
    configure_logging,
    metrics,
    request_id_context,
    safe_correlation_id,
    trace_id_context,
)
from hunt_board.dashboard.api import router as dashboard_router
from hunt_board.notifications.api import router as notifications_router
from hunt_board.searches.api import router as searches_router
from hunt_board.tracking.api import router as tracking_router
from hunt_board.auth.api import admin_router as auth_admin_router
from hunt_board.auth.api import router as auth_router


def create_app() -> FastAPI:
    settings = get_settings()
    validate_runtime_settings(settings)
    configure_logging(
        environment=settings.environment,
        release=settings.release,
        process_name=settings.process_name,
    )
    logger = logging.getLogger("hunt_board")
    app = FastAPI(title="Hunt Board", version="0.6.2")

    @app.exception_handler(SQLAlchemyError)
    async def database_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        metrics.database_error()
        request_id = getattr(request.state, "request_id", None)
        original = getattr(exc, "orig", None)
        logger.error(
            "database.error",
            extra={
                "event_name": "database.error",
                "event_data": {
                    "environment": get_settings().environment,
                    "request_id": request_id,
                    "trace_id": getattr(request.state, "trace_id", None),
                    "route": request.url.path,
                    "error_type": type(exc).__name__,
                    "database_error_type": type(original).__name__ if original else None,
                    "database_error_message": str(original or exc),
                },
            },
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "A database error occurred", "request_id": request_id},
        )

    @app.middleware("http")
    async def request_observability(request: Request, call_next):
        started = perf_counter()
        request_id = safe_correlation_id(request.headers.get("X-Request-ID"))
        trace_id = safe_correlation_id(
            request.headers.get("X-Trace-ID") or request.headers.get("X-Correlation-ID")
        )
        request.state.request_id = request_id
        request.state.trace_id = trace_id
        request_id_context.set(request_id)
        trace_id_context.set(trace_id)
        response = await call_next(request)
        duration = perf_counter() - started
        route = request.scope.get("route")
        route_label = getattr(route, "path", "<unmatched>")
        metrics.observe_request(request.method, route_label, response.status_code, duration)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Trace-ID"] = trace_id
        if request.url.path == "/app" or request.url.path.startswith("/app/"):
            response.headers["Cache-Control"] = "no-store"
        event_name = (
            "admin.mutation"
            if request.url.path.startswith(("/admin/", "/api/admin/"))
            and request.method in {"POST", "PUT", "PATCH", "DELETE"}
            else "http.request"
        )
        logger.info(
            event_name,
            extra={
                "event_name": event_name,
                "event_data": {
                    "environment": get_settings().environment,
                    "request_id": request_id,
                    "trace_id": trace_id,
                    "route": route_label,
                    "method": request.method,
                    "status": response.status_code,
                    "duration_ms": round(duration * 1000, 3),
                },
            },
        )
        return response

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/live")
    def health_live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/db")
    def health_db(db: Session = Depends(get_db)) -> dict[str, str]:
        try:
            db.execute(text("SELECT 1"))
        except SQLAlchemyError as exc:
            raise HTTPException(status_code=503, detail="Database unavailable") from exc
        return {"status": "ok"}

    @app.get("/health/ready")
    def health_ready(db: Session = Depends(get_db)) -> dict[str, str]:
        try:
            db.execute(text("SELECT 1"))
            db.execute(select(JobPosting.id).limit(1))
            db.execute(select(Source.id).limit(1))
            db.execute(select(ScrapeRun.id).limit(1))
            db.execute(select(IngestionQuarantine.id).limit(1))
            db.execute(select(JobLifecycleEvent.id).limit(1))
            db.execute(select(SavedSearch.id).limit(1))
            if db.get_bind().dialect.name == "postgresql":
                db.execute(text("SELECT search_vector FROM job_postings LIMIT 0"))
        except SQLAlchemyError as exc:
            raise HTTPException(status_code=503, detail="Database schema unavailable") from exc
        return {"status": "ok"}

    @app.get("/health/ingestion", response_model=IngestionHealthRead)
    def health_ingestion(db: Session = Depends(get_db)) -> dict:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=get_settings().stale_run_minutes)
        last_run = db.scalar(select(ScrapeRun).order_by(ScrapeRun.started_at.desc(), ScrapeRun.id.desc()).limit(1))
        stale_running_runs = db.scalar(
            select(func.count(ScrapeRun.id)).where(
                ScrapeRun.status == "running",
                ScrapeRun.started_at < cutoff,
            )
        ) or 0
        active_running_runs = db.scalar(
            select(func.count(ScrapeRun.id)).where(
                ScrapeRun.status == "running",
                ScrapeRun.started_at >= cutoff,
            )
        ) or 0
        due_sources = db.scalar(
            select(func.count(Source.id)).where(
                Source.enabled.is_(True),
                or_(Source.next_due_at.is_(None), Source.next_due_at <= now),
            )
        ) or 0
        unhealthy_sources = db.scalar(
            select(func.count(Source.id)).where(
                Source.enabled.is_(True),
                Source.health_status == "unhealthy",
            )
        ) or 0
        last_successful_at = db.scalar(
            select(func.max(ScrapeRun.finished_at)).where(
                ScrapeRun.status == "completed"
            )
        )
        expected_cutoff = now - timedelta(seconds=get_settings().scheduler_interval_seconds * 2)
        scan_overdue = bool(
            last_run
            and last_run.started_at < expected_cutoff
            and (last_successful_at is None or last_successful_at < expected_cutoff)
        )
        if stale_running_runs or scan_overdue:
            status = "stale"
        elif unhealthy_sources or (last_run and last_run.status in {"failed", "abandoned", "completed_with_errors"}):
            status = "degraded"
        else:
            status = "ok"
        return {
            "status": status,
            "run_in_progress": bool(active_running_runs),
            "last_run": None
            if last_run is None
            else {
                "id": last_run.id,
                "status": last_run.status,
                "started_at": last_run.started_at,
                "finished_at": last_run.finished_at,
            },
            "last_successful_at": last_successful_at,
            "due_sources": due_sources,
            "unhealthy_sources": unhealthy_sources,
            "stale_running_runs": stale_running_runs,
        }

    app.include_router(jobs_router)
    app.include_router(public_router)
    app.include_router(jobs_router, prefix="/api", include_in_schema=False)
    app.include_router(preferences_router)
    app.include_router(preferences_router, prefix="/api", include_in_schema=False)
    app.include_router(tracking_router)
    app.include_router(tracking_router, prefix="/api", include_in_schema=False)
    app.include_router(notifications_router)
    app.include_router(notifications_router, prefix="/api", include_in_schema=False)
    app.include_router(searches_router)
    app.include_router(searches_router, prefix="/api", include_in_schema=False)
    app.include_router(dashboard_router)
    app.include_router(dashboard_router, prefix="/api", include_in_schema=False)
    app.include_router(auth_router)
    app.include_router(auth_admin_router)
    app.include_router(auth_admin_router, prefix="/api", include_in_schema=False)
    app.include_router(ingest_router)
    app.include_router(admin_router)
    app.include_router(admin_router, prefix="/api", include_in_schema=False)
    app.include_router(metrics_router)
    web_root = Path(__file__).parent / "web" / "static"
    app.mount("/app", StaticFiles(directory=web_root, html=True), name="app")
    return app


app = create_app()
