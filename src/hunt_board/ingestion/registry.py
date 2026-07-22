from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from hunt_board.db.models import Source
from hunt_board.ingestion.sources import load_sources


@dataclass(frozen=True)
class SourceSyncResult:
    created: int
    updated: int
    disabled: int


def sync_sources_from_yaml(db: Session, sources_path: str, *, commit: bool = True) -> SourceSyncResult:
    configs = load_sources(sources_path)
    existing_by_slug = {source.slug: source for source in db.scalars(select(Source)).all()}
    configured_slugs = {config.slug for config in configs}
    created = 0
    updated = 0
    for config in configs:
        source = existing_by_slug.get(config.slug)
        if source is None:
            source = Source(slug=config.slug, name=config.name, ats=config.ats, company_name=config.company_name)
            db.add(source)
            created += 1
        else:
            updated += 1
        source.name = config.name
        source.ats = config.ats
        source.company_name = config.company_name
        source.company_logo_url = config.company_logo_url
        source.careers_url = config.careers_url
        source.enabled = config.enabled
        source.priority = config.priority
        source.categories = config.categories
        source.notes = config.notes
        source.config_json = config.config

    disabled = 0
    for slug, source in existing_by_slug.items():
        if slug not in configured_slugs and source.enabled:
            source.enabled = False
            disabled += 1
    if commit:
        db.commit()
    else:
        db.flush()
    return SourceSyncResult(created=created, updated=updated, disabled=disabled)
