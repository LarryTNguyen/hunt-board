from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from hunt_board.admin.api import router as admin_router
from hunt_board.api.ingest import router as ingest_router
from hunt_board.api.jobs import router as jobs_router
from hunt_board.db.session import get_db


def create_app() -> FastAPI:
    app = FastAPI(title="Hunt Board", version="0.1.0")

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
    app.include_router(ingest_router)
    app.include_router(admin_router)
    app.include_router(admin_router, prefix="/api", include_in_schema=False)
    return app


app = create_app()
