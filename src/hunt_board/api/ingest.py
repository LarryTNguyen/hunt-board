from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from hunt_board.api.schemas import IngestRunRequest, IngestRunResponse
from hunt_board.auth.dependencies import require_admin
from hunt_board.core.config import get_settings
from hunt_board.db.session import get_db
from hunt_board.ingestion.service import IngestionService
from hunt_board.ingestion.lock import IngestionAlreadyRunningError

router = APIRouter(
    prefix="/api/ingest",
    tags=["ingestion"],
    dependencies=[Depends(require_admin)],
)


@router.post("/run", response_model=IngestRunResponse)
async def run_ingestion(payload: IngestRunRequest, db: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    service = IngestionService(
        str(settings.sources_path),
        settings.http_timeout_seconds,
        settings.source_concurrency,
        settings.http_max_retries,
        settings.http_retry_backoff_seconds,
        stale_run_minutes=settings.stale_run_minutes,
    )
    try:
        summary = await service.run(db, payload.source_slugs, payload.dry_run)
    except IngestionAlreadyRunningError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return asdict(summary)
