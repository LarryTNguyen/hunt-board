from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from hunt_board.admin.api import router as admin_router
from hunt_board.api.ingest import router as ingest_router
from hunt_board.api.jobs import router as jobs_router
from hunt_board.api.preferences import router as preferences_router
from hunt_board.db.session import get_db
from hunt_board.notifications.api import router as notifications_router
from hunt_board.tracking.api import router as tracking_router


def create_app() -> FastAPI:
    app = FastAPI(title="Hunt Board", version="0.3.0")

    @app.middleware("http")
    async def prevent_stale_frontend_assets(request: Request, call_next):
        response = await call_next(request)
        if request.url.path == "/app" or request.url.path.startswith("/app/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/db")
    def health_db(db: Session = Depends(get_db)) -> dict[str, str]:
        try:
            db.execute(text("SELECT 1"))
        except SQLAlchemyError as exc:
            raise HTTPException(status_code=503, detail="Database unavailable") from exc
        return {"status": "ok"}

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
