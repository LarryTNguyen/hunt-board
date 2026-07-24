from __future__ import annotations

from pathlib import Path

import pytest

from hunt_board.ingestion.sources import load_sources, select_sources

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_load_sources_validates_unique_slugs() -> None:
    with pytest.raises(ValueError, match="unique"):
        load_sources(FIXTURE_DIR / "sources_duplicate_slugs.yaml")


def test_select_sources_defaults_to_enabled() -> None:
    sources = load_sources(FIXTURE_DIR / "sources_enabled_disabled.yaml")

    assert [source.slug for source in select_sources(sources)] == ["active"]
    assert [source.slug for source in select_sources(sources, ["disabled"])] == ["disabled"]


def test_load_sources_accepts_milestone_shape() -> None:
    source = load_sources(FIXTURE_DIR / "sources_milestone_shape.yaml")[0]

    assert source.slug == "stripe"
    assert source.ats == "greenhouse"
    assert source.priority == 5
    assert source.config["board_token"] == "stripe"
    assert source.poll_interval_minutes is None
    assert source.effective_poll_interval_minutes == 360
    assert source.close_after_missed_runs == 12
