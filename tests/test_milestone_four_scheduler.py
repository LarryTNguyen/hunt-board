from __future__ import annotations

import asyncio
from contextlib import nullcontext
from dataclasses import replace
from types import SimpleNamespace

import pytest

from hunt_board.core.config import get_settings
from hunt_board.ingestion.lock import IngestionAlreadyRunningError
from hunt_board.ingestion.scheduler import IngestionScheduler, SchedulerTickResult


class FakeService:
    def __init__(self, outcomes):
        self.outcomes = outcomes

    async def run(self, db, triggered_by):
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _summary(sources=None, status="completed"):
    return SimpleNamespace(sources_requested=sources or [], status=status, scrape_run_id=12)


@pytest.mark.asyncio()
async def test_scheduler_tick_runs_due_sources_and_skips_lock_contention() -> None:
    settings = get_settings()
    service = FakeService([_summary(["acme"]), IngestionAlreadyRunningError("busy")])
    scheduler = IngestionScheduler(
        settings,
        session_factory=lambda: nullcontext(object()),
        service_factory=lambda _: service,
    )
    first = await scheduler.tick()
    second = await scheduler.tick()
    assert first == SchedulerTickResult(status="completed", sources_requested=1, scrape_run_id=12)
    assert second.status == "skipped_lock_contention"


@pytest.mark.asyncio()
async def test_scheduler_continues_after_failed_tick_and_stops_cleanly() -> None:
    settings = replace(get_settings(), scheduler_interval_seconds=0.001, scheduler_run_on_startup=True)
    stop = asyncio.Event()

    class RecordingScheduler(IngestionScheduler):
        calls = 0

        async def tick(self):
            self.calls += 1
            if self.calls == 2:
                stop.set()
            return SchedulerTickResult(status="failed" if self.calls == 1 else "completed")

    scheduler = RecordingScheduler(settings)
    result = await scheduler.run(stop)
    assert scheduler.calls == 2
    assert result["status"] == "stopped"
    assert result["ticks"] == 2
