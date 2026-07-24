"""add milestone four discovery search and operations indexes

Revision ID: 202607220009
Revises: 202607220008
Create Date: 2026-07-22 18:00:00.000000
"""

from __future__ import annotations

from alembic import op


revision = "202607220009"
down_revision = "202607220008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            ALTER TABLE job_postings
            ADD COLUMN search_vector tsvector
            GENERATED ALWAYS AS (
                setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
                setweight(to_tsvector('english', coalesce(company_name, '')), 'A') ||
                setweight(to_tsvector('english', coalesce(location, '') || ' ' || coalesce(department, '')), 'B') ||
                setweight(to_tsvector('english', coalesce(description_text, '')), 'C')
            ) STORED
            """
        )
        op.create_index(
            "ix_job_postings_search_vector_gin",
            "job_postings",
            ["search_vector"],
            postgresql_using="gin",
        )

    op.create_index(
        "ix_job_postings_feed_default",
        "job_postings",
        ["active", "duplicate_status", "ranking_score", "id"],
    )
    op.create_index("ix_job_postings_source_id", "job_postings", ["source_id"])
    op.create_index("ix_sources_enabled_next_due", "sources", ["enabled", "next_due_at"])
    op.create_index("ix_scrape_runs_started_status", "scrape_runs", ["started_at", "status"])


def downgrade() -> None:
    op.drop_index("ix_scrape_runs_started_status", table_name="scrape_runs")
    op.drop_index("ix_sources_enabled_next_due", table_name="sources")
    op.drop_index("ix_job_postings_source_id", table_name="job_postings")
    op.drop_index("ix_job_postings_feed_default", table_name="job_postings")
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_index("ix_job_postings_search_vector_gin", table_name="job_postings")
        op.execute("ALTER TABLE job_postings DROP COLUMN search_vector")
