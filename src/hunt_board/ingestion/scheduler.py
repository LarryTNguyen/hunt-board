from __future__ import annotations

import asyncio
import logging
import signal
from dataclasses import asdict, dataclass
from typing import Any, Callable

from hunt_board.core.config import Settings
from hunt_board.db.session import SessionLocal
from hunt_board.ingestion.lock import IngestionAlreadyRunningError
from hunt_board.ingestion.service import IngestionService


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SchedulerTickResult:
    status: str
    sources_requested: int = 0
    scrape_run_id: int | None = None
    error: str | None = None


class IngestionScheduler:
    def __init__(
        self,
        settings: Settings,
        *,
        session_factory: Callable[[], Any] = SessionLocal,
        service_factory: Callable[[Settings], IngestionService] | None = None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.service_factory = service_factory or _service_from_settings

    async def tick(self) -> SchedulerTickResult:
        try:
            with self.session_factory() as db:
                summary = await self.service_factory(self.settings).run(db, triggered_by="scheduler")
        except IngestionAlreadyRunningError:
            result = SchedulerTickResult(status="skipped_lock_contention")
            logger.info("Scheduler tick skipped: another real ingestion run holds the lock")
            return result
        except Exception as exc:
            result = SchedulerTickResult(status="failed", error=f"{type(exc).__name__}: {exc}"[:500])
            logger.exception("Scheduler tick failed; the scheduler will continue")
            return result

        if not summary.sources_requested:
            result = SchedulerTickResult(status="skipped_no_sources_due")
        else:
            result = SchedulerTickResult(
                status=summary.status,
                sources_requested=len(summary.sources_requested),
                scrape_run_id=summary.scrape_run_id,
            )
        logger.info(
            "Scheduler tick result=%s sources=%s run_id=%s",
            result.status,
            result.sources_requested,
            result.scrape_run_id,
        )
        return result

    async def run(self, stop_event: asyncio.Event | None = None) -> dict:
        stop = stop_event or asyncio.Event()
        ticks = 0
        last_result: SchedulerTickResult | None = None
        if not self.settings.scheduler_enabled:
            logger.info("Scheduler is disabled by configuration")
            return {"status": "disabled", "ticks": 0, "last_tick": None}
        logger.info(
            "Scheduler started interval_seconds=%s run_on_startup=%s",
            self.settings.scheduler_interval_seconds,
            self.settings.scheduler_run_on_startup,
        )
        if self.settings.scheduler_run_on_startup and not stop.is_set():
            last_result = await self.tick()
            ticks += 1
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.settings.scheduler_interval_seconds)
            except TimeoutError:
                last_result = await self.tick()
                ticks += 1
        logger.info("Scheduler stopped cleanly after %s tick(s)", ticks)
        return {
            "status": "stopped",
            "ticks": ticks,
            "last_tick": asdict(last_result) if last_result else None,
        }


def _service_from_settings(settings: Settings) -> IngestionService:
    return IngestionService(
        str(settings.sources_path),
        settings.http_timeout_seconds,
        settings.source_concurrency,
        settings.http_max_retries,
        settings.http_retry_backoff_seconds,
        stale_run_minutes=settings.stale_run_minutes,
    )


async def run_scheduler(settings: Settings) -> dict:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    registered: list[signal.Signals] = []

    def request_stop() -> None:
        stop_event.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, request_stop)
            registered.append(signum)
        except (NotImplementedError, RuntimeError):
            # Windows console delivery is handled by asyncio.run/KeyboardInterrupt.
            pass
    try:
        return await IngestionScheduler(settings).run(stop_event)
    finally:
        for signum in registered:
            loop.remove_signal_handler(signum)
