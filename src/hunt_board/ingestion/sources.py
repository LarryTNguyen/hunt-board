from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


ATSName = Literal["greenhouse", "lever", "ashby"]


class SourceConfig(BaseModel):
    slug: str
    name: str
    ats: ATSName
    company_name: str
    company_logo_url: str | None = None
    careers_url: str | None = None
    enabled: bool = True
    priority: int = 0
    categories: list[str] = Field(default_factory=list)
    notes: str = ""
    config: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def accept_milestone_and_legacy_shapes(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        ats = data.get("ats", data.get("ats_type"))
        ats_slug = data.get("ats_slug")
        data.setdefault("ats", ats)
        data.setdefault("slug", ats_slug)
        data.setdefault("name", data.get("company_name"))
        config = dict(data.get("config") or {})
        if ats_slug and ats == "greenhouse":
            config.setdefault("board_token", ats_slug)
        elif ats_slug and ats == "lever":
            config.setdefault("site", ats_slug)
        elif ats_slug and ats == "ashby":
            config.setdefault("organization", ats_slug)
        data["config"] = config
        return data

    @field_validator("priority", mode="before")
    @classmethod
    def parse_priority(cls, value: Any) -> int:
        if isinstance(value, str):
            priorities = {"low": 1, "medium": 3, "high": 5}
            try:
                return priorities[value.lower()]
            except KeyError as exc:
                raise ValueError("priority must be high, medium, low, or an integer from 0 to 5") from exc
        parsed = int(value)
        if not 0 <= parsed <= 5:
            raise ValueError("priority must be between 0 and 5")
        return parsed


class SourceFile(BaseModel):
    sources: list[SourceConfig]


def load_sources(path: str | Path) -> list[SourceConfig]:
    source_path = Path(path)
    with source_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if isinstance(raw, list):
        raw = {"sources": raw}
    source_file = SourceFile.model_validate(raw)
    slugs = [source.slug for source in source_file.sources]
    if len(slugs) != len(set(slugs)):
        raise ValueError("Source slugs must be unique")
    return source_file.sources


def select_sources(sources: list[SourceConfig], requested_slugs: list[str] | None = None) -> list[SourceConfig]:
    if requested_slugs:
        requested = set(requested_slugs)
        selected = [source for source in sources if source.slug in requested]
        missing = sorted(requested - {source.slug for source in selected})
        if missing:
            raise ValueError(f"Unknown source slug(s): {', '.join(missing)}")
        return selected
    return [source for source in sources if source.enabled]
