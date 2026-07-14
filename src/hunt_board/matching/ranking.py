from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from hunt_board.ingestion.adapters.base import NormalizedJob
from hunt_board.jobs.dedupe import normalize_text


ROLE_GROUPS = {
    "software_engineering": {
        "software engineer", "software developer", "swe", "backend", "frontend", "full stack",
        "full-stack", "platform", "infrastructure",
    },
    "data_science": {"data scientist", "data science", "data analyst", "analytics", "machine learning", "ml"},
    "machine_learning": {
        "machine learning engineer", "ml engineer", "ai engineer", "applied scientist", "research engineer",
    },
    "backend": {"backend", "back end", "platform", "infrastructure", "distributed systems", "api"},
    "full_stack": {"full stack", "full-stack", "frontend", "backend", "web developer"},
    # Backward-compatible names accepted by early preference fixtures.
    "fullstack": {"full stack", "full-stack", "frontend", "backend", "web developer"},
    "data": {"data scientist", "data science", "data analyst", "analytics", "machine learning", "ml"},
}


class UserPreferences(BaseModel):
    include_keywords: list[str] = Field(default_factory=lambda: ["backend engineer", "software engineer", "python"])
    exclude_keywords: list[str] = Field(default_factory=lambda: ["manager", "principal", "staff"])
    role_groups: list[str] = Field(default_factory=lambda: ["backend"])
    preferred_levels: list[str] = Field(default_factory=lambda: ["intern", "entry", "junior", "mid"])
    preferred_locations: list[str] = Field(default_factory=lambda: ["remote", "united states", "us"])
    home_location: str = "San Jose"
    radius_miles: int = 60
    country: str = "USA"
    remote_allowed: bool = True
    minimum_score_threshold: float = Field(default=60, ge=0, le=100)


@dataclass(frozen=True)
class RankingResult:
    score: float
    reasons: list[str] = field(default_factory=list)
    matched: bool = True


def _contains_phrase(title: str, phrase: str) -> bool:
    normalized_phrase = normalize_text(phrase)
    if not normalized_phrase:
        return False
    return f" {normalized_phrase} " in f" {title} "


def _level_score(title: str, preferences: UserPreferences) -> tuple[float, str]:
    senior_tokens = {"senior", "sr", "staff", "principal", "lead", "manager", "director"}
    junior_tokens = {"intern", "entry", "junior", "jr", "associate", "new grad"}
    if any(token in title.split() for token in senior_tokens):
        return (6, "senior-or-lead title")
    if any(token in title for token in junior_tokens):
        return (20, "preferred early-career level")
    if "mid" in preferences.preferred_levels:
        return (16, "mid-level compatible title")
    return (10, "level unspecified")


def rank_job(job: NormalizedJob, preferences: UserPreferences | None = None, source_priority: int = 0) -> RankingResult:
    prefs = preferences or UserPreferences()
    title = normalize_text(job.title) or ""

    include_hits = [keyword for keyword in prefs.include_keywords if _contains_phrase(title, keyword)]
    group_hits = [
        group
        for group in prefs.role_groups
        if any(_contains_phrase(title, keyword) for keyword in ROLE_GROUPS.get(group, set()))
    ]
    exclude_hits = [keyword for keyword in prefs.exclude_keywords if _contains_phrase(title, keyword)]

    specific_include_hits = [keyword for keyword in include_hits if len((normalize_text(keyword) or "").split()) > 1]
    if exclude_hits and not specific_include_hits:
        return RankingResult(0, [f"excluded by title keyword: {', '.join(exclude_hits)}"], matched=False)
    if prefs.include_keywords and not include_hits and not group_hits:
        return RankingResult(0, ["no include keyword or role group matched title"], matched=False)

    reasons: list[str] = []
    title_score = 0.0
    if include_hits:
        title_score = 40.0
        reasons.append(f"exact include title match: {', '.join(include_hits)}")
    elif group_hits:
        title_score = 30.0
        reasons.append(f"role group title match: {', '.join(group_hits)}")

    level_score, level_reason = _level_score(title, prefs)
    reasons.append(level_reason)

    now = datetime.now(timezone.utc)
    seen_at = job.posted_at or now
    if seen_at.tzinfo is None:
        seen_at = seen_at.replace(tzinfo=timezone.utc)
    age_days = max((now - seen_at).days, 0)
    freshness_score = max(0, 20 - min(age_days, 20))
    reasons.append(f"freshness age_days={age_days}")

    location_value = normalize_text(" ".join(filter(None, [job.location, job.workplace_type]))) or ""
    location_score = 15 if any(_contains_phrase(location_value, location) for location in prefs.preferred_locations) else 6
    reasons.append("preferred location/work type" if location_score == 15 else "location/work type not preferred")

    priority_score = min(max(source_priority, 0), 5)
    if priority_score:
        reasons.append(f"source priority {priority_score}")

    score = round(title_score + level_score + freshness_score + location_score + priority_score, 2)
    return RankingResult(min(score, 100), reasons, matched=True)
