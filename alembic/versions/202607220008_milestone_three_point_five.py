"""harden ingestion lifecycle and source policies

Revision ID: 202607220008
Revises: 202607210007
Create Date: 2026-07-22 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "202607220008"
down_revision = "202607210007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("poll_interval_minutes", sa.Integer(), nullable=True))
    op.add_column(
        "sources",
        sa.Column("close_after_missed_runs", sa.Integer(), nullable=False, server_default="12"),
    )
    op.add_column("scrape_runs", sa.Column("error_message", sa.Text(), nullable=True))
    op.execute(
        """
        UPDATE sources
        SET poll_interval_minutes = CASE
            WHEN priority >= 5 THEN 360
            WHEN priority >= 3 THEN 720
            ELSE 1440
        END
        """
    )
    op.alter_column("sources", "close_after_missed_runs", server_default=None)


def downgrade() -> None:
    op.drop_column("scrape_runs", "error_message")
    op.drop_column("sources", "close_after_missed_runs")
    op.drop_column("sources", "poll_interval_minutes")
