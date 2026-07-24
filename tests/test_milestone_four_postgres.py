from __future__ import annotations

import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, inspect, literal_column, select, text
from sqlalchemy.orm import Session

from hunt_board.db.models import JobPosting, Source
from hunt_board.ingestion.lock import INGESTION_ADVISORY_LOCK_KEY


POSTGRES_URL = os.environ.get("HUNT_BOARD_TEST_POSTGRES_URL")
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(not POSTGRES_URL, reason="set HUNT_BOARD_TEST_POSTGRES_URL for PostgreSQL verification"),
]


def test_postgres_search_index_relevance_filters_and_advisory_lock() -> None:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", POSTGRES_URL)
    command.upgrade(config, "head")
    engine = create_engine(POSTGRES_URL)
    indexes = {item["name"] for item in inspect(engine).get_indexes("job_postings")}
    assert "ix_job_postings_search_vector_gin" in indexes

    slug = f"m4-{uuid4().hex[:10]}"
    with engine.connect() as connection, connection.begin(), Session(connection) as db:
        source = Source(slug=slug, name=slug, ats="greenhouse", company_name="Milestone Four")
        db.add(source)
        db.flush()
        db.add_all(
            [
                JobPosting(source_id=source.id, source_slug=slug, company_name=source.company_name, external_job_id="title", title="Zephyr Platform Engineer", normalized_title="zephyr platform engineer", location="Remote", normalized_location="remote", location_country_code="US", description_text="Build APIs", raw_json={}, ranking_score=90),
                JobPosting(source_id=source.id, source_slug=slug, company_name=source.company_name, external_job_id="description", title="Systems Engineer", normalized_title="systems engineer", location="Toronto", normalized_location="toronto", location_country_code="CA", description_text="Own zephyr observability pipelines", raw_json={}, ranking_score=70),
            ]
        )
        db.flush()
        query = func.websearch_to_tsquery("english", "zephyr")
        vector = literal_column("job_postings.search_vector")
        ranked = db.execute(
            select(JobPosting.title)
            .where(JobPosting.source_id == source.id, vector.op("@@")(query))
            .order_by(text("ts_rank_cd(job_postings.search_vector, websearch_to_tsquery('english', 'zephyr')) DESC"))
        ).scalars().all()
        assert ranked == ["Zephyr Platform Engineer", "Systems Engineer"]
        filtered = db.execute(
            select(JobPosting.title).where(
                JobPosting.source_id == source.id,
                JobPosting.location_country_code == "CA",
                vector.op("@@")(query),
            )
        ).scalars().all()
        assert filtered == ["Systems Engineer"]

    with engine.connect() as first, engine.connect() as second:
        assert first.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": INGESTION_ADVISORY_LOCK_KEY}) is True
        assert second.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": INGESTION_ADVISORY_LOCK_KEY}) is False
        first.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": INGESTION_ADVISORY_LOCK_KEY})
    engine.dispose()
