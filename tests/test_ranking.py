from __future__ import annotations

from datetime import datetime, timezone

from hunt_board.ingestion.adapters.base import NormalizedJob
from hunt_board.matching.ranking import UserPreferences, rank_job


def _job(title: str) -> NormalizedJob:
    return NormalizedJob(
        source_slug="acme",
        company_name="Acme",
        external_job_id="1",
        title=title,
        location="Remote, United States",
        department="Engineering",
        employment_type="Full-time",
        workplace_type="remote",
        apply_url="https://jobs.example.com/1",
        description_html=None,
        description_text=None,
        raw_json={"id": "1"},
        posted_at=datetime.now(timezone.utc),
    )


def test_exact_include_phrase_beats_exclude() -> None:
    result = rank_job(
        _job("Principal Backend Engineer"),
        UserPreferences(include_keywords=["backend engineer"], exclude_keywords=["principal"]),
        source_priority=5,
    )

    assert result.matched is True
    assert result.score > 70


def test_exclude_applies_after_include_matching() -> None:
    result = rank_job(
        _job("Principal Architect"),
        UserPreferences(include_keywords=["backend engineer"], exclude_keywords=["principal"]),
    )

    assert result.matched is False
    assert result.score == 0


def test_general_include_does_not_beat_specific_exclude() -> None:
    result = rank_job(
        _job("Principal Engineer"),
        UserPreferences(include_keywords=["engineer"], exclude_keywords=["principal engineer"]),
    )

    assert result.matched is False
