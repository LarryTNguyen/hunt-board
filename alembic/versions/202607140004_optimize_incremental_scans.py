"""optimize incremental job scans

Revision ID: 202607140004
Revises: 202607140003
Create Date: 2026-07-14 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "202607140004"
down_revision = "202607140003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sources", sa.Column("last_error", sa.Text(), nullable=True))

    op.add_column(
        "scrape_runs",
        sa.Column("total_unchanged_jobs", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "scrape_source_runs",
        sa.Column("unchanged_jobs", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_index("ix_job_postings_posted_at", "job_postings", ["posted_at"])
    op.create_index("ix_job_postings_company_name", "job_postings", ["company_name"])
    op.create_index("ix_job_postings_title", "job_postings", ["title"])
    op.create_index("ix_job_postings_location", "job_postings", ["location"])


def downgrade() -> None:
    op.drop_index("ix_job_postings_location", table_name="job_postings")
    op.drop_index("ix_job_postings_title", table_name="job_postings")
    op.drop_index("ix_job_postings_company_name", table_name="job_postings")
    op.drop_index("ix_job_postings_posted_at", table_name="job_postings")

    op.drop_column("scrape_source_runs", "unchanged_jobs")
    op.drop_column("scrape_runs", "total_unchanged_jobs")
    op.drop_column("sources", "last_error")
    op.drop_column("sources", "last_checked_at")
