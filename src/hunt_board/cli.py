from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict

from hunt_board.core.config import get_settings
from hunt_board.db.seed import seed_milestone_one
from hunt_board.db.session import SessionLocal
from hunt_board.ingestion.registry import sync_sources_from_yaml
from hunt_board.ingestion.service import IngestionService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hunt-board")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("seed", help="Seed the MVP user, preferences, statuses, and sources")
    commands.add_parser("sync-sources", help="Synchronize job sources from YAML")
    ingest = commands.add_parser("ingest", help="Run ATS ingestion")
    ingest.add_argument("--source", action="append", dest="sources")
    ingest.add_argument("--dry-run", action="store_true")
    return parser


async def _ingest(sources: list[str] | None, dry_run: bool) -> dict:
    settings = get_settings()
    with SessionLocal() as db:
        service = IngestionService(str(settings.sources_path), settings.http_timeout_seconds)
        return asdict(await service.run(db, sources, dry_run, triggered_by="cli"))


def main() -> None:
    args = build_parser().parse_args()
    settings = get_settings()
    if args.command == "ingest":
        result = asyncio.run(_ingest(args.sources, args.dry_run))
    else:
        with SessionLocal() as db:
            if args.command == "seed":
                result = asdict(seed_milestone_one(db, settings.default_user_email, str(settings.sources_path)))
            else:
                result = asdict(sync_sources_from_yaml(db, str(settings.sources_path)))
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
