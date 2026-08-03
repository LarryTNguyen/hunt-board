from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict

from hunt_board.core.config import get_settings
from hunt_board.db.seed import seed_milestone_one
from hunt_board.db.session import SessionLocal
from hunt_board.ingestion.registry import sync_sources_from_yaml
from hunt_board.ingestion.service import IngestionService
from hunt_board.ingestion.retention import purge_expired_raw_payloads
from hunt_board.ingestion.scheduler import run_scheduler
from hunt_board.jobs.classification_service import coverage_report, reclassify_jobs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hunt-board")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("seed", help="Seed the MVP user, preferences, statuses, saved route, and sources")
    commands.add_parser("sync-sources", help="Synchronize job sources from YAML")
    ingest = commands.add_parser("ingest", help="Run ATS ingestion")
    ingest.add_argument("--source", action="append", dest="sources")
    ingest.add_argument("--dry-run", action="store_true")
    commands.add_parser("scheduler", help="Run due-source ingestion on a separate process interval")
    purge = commands.add_parser("purge-expired-raw", help="Purge expired ATS raw payloads")
    purge.add_argument("--dry-run", action="store_true")
    reclassify = commands.add_parser("reclassify-jobs", help="Reclassify catalog jobs while preserving admin overrides")
    reclassify.add_argument("--replace-overrides", action="store_true")
    commands.add_parser("coverage-report", help="Summarize active jobs by family, ATS, and company")
    return parser


async def _ingest(sources: list[str] | None, dry_run: bool) -> dict:
    settings = get_settings()
    with SessionLocal() as db:
        service = IngestionService(
            str(settings.sources_path),
            settings.http_timeout_seconds,
            settings.source_concurrency,
            settings.http_max_retries,
            settings.http_retry_backoff_seconds,
            stale_run_minutes=settings.stale_run_minutes,
        )
        return asdict(await service.run(db, sources, dry_run, triggered_by="cli"))


def main() -> None:
    args = build_parser().parse_args()
    settings = get_settings()
    try:
        if args.command == "ingest":
            result = asyncio.run(_ingest(args.sources, args.dry_run))
        elif args.command == "scheduler":
            result = asyncio.run(run_scheduler(settings))
        else:
            with SessionLocal() as db:
                if args.command == "seed":
                    result = asdict(
                        seed_milestone_one(
                            db,
                            settings.default_user_email,
                            str(settings.sources_path),
                            environment=settings.environment,
                        )
                    )
                elif args.command == "sync-sources":
                    result = asdict(sync_sources_from_yaml(db, str(settings.sources_path)))
                elif args.command == "reclassify-jobs":
                    result = asdict(reclassify_jobs(db, include_overrides=args.replace_overrides))
                elif args.command == "coverage-report":
                    result = coverage_report(db)
                else:
                    result = asdict(purge_expired_raw_payloads(db, dry_run=args.dry_run))
    except KeyboardInterrupt:
        result = {"status": "stopped", "reason": "keyboard interrupt"}
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2), file=sys.stderr)
        raise SystemExit(1) from exc
    print(json.dumps(result, indent=2, default=str))
    if result.get("status") == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
