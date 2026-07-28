from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from hunt_board.admin.api import router as admin_router
from hunt_board.api.schemas import IngestionHealthRead
from hunt_board.api.ingest import router as ingest_router
from hunt_board.api.jobs import router as jobs_router
from hunt_board.api.preferences import router as preferences_router
from hunt_board.db.session import get_db
from hunt_board.db.models import JobPosting, ScrapeRun, Source
from hunt_board.core.config import get_settings
from hunt_board.notifications.api import router as notifications_router
from hunt_board.tracking.api import router as tracking_router


def create_app() -> FastAPI:
    app = FastAPI(title="Hunt Board", version="0.4.1")

    @app.middleware("http")
    async def prevent_stale_frontend_assets(request: Request, call_next):
        response = await call_next(request)
        if request.url.path == "/app" or request.url.path.startswith("/app/"):
            response.headers["Cache-Control"] = "no-store"
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
        if stale_running_runs:
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
    app.include_router(jobs_router, prefix="/api", include_in_schema=False)
    app.include_router(preferences_router)
    app.include_router(preferences_router, prefix="/api", include_in_schema=False)
    app.include_router(tracking_router)
    app.include_router(tracking_router, prefix="/api", include_in_schema=False)
    app.include_router(notifications_router)
    app.include_router(notifications_router, prefix="/api", include_in_schema=False)
    app.include_router(ingest_router)
    app.include_router(admin_router)
    app.include_router(admin_router, prefix="/api", include_in_schema=False)
    web_root = Path(__file__).parent / "web" / "static"
    app.mount("/app", StaticFiles(directory=web_root, html=True), name="app")
    return app


app = create_app()
