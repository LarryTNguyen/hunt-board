from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from hunt_board.api.schemas import IngestRunRequest, IngestRunResponse
from hunt_board.core.config import get_settings
from hunt_board.db.session import get_db
from hunt_board.ingestion.service import IngestionService

router = APIRouter(prefix="/api/ingest", tags=["ingestion"])


@router.post("/run", response_model=IngestRunResponse)
async def run_ingestion(payload: IngestRunRequest, db: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    service = IngestionService(str(settings.sources_path), settings.http_timeout_seconds)
    summary = await service.run(db, payload.source_slugs, payload.dry_run)
    return asdict(summary)

