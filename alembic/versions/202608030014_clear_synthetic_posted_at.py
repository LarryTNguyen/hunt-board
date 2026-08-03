"""Clear posting timestamps synthesized from first-seen time.

Revision ID: 202608030014
Revises: 202608030013
Create Date: 2026-08-03 00:00:01.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "202608030014"
down_revision = "202608030013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Earlier ingestion used first_seen_at as a fallback for missing ATS data.
    # Exact equality identifies those synthesized values without touching real
    # publication timestamps obtained from the source.
    op.execute(
        sa.text(
            "UPDATE job_postings "
            "SET posted_at = NULL "
            "WHERE posted_at = first_seen_at"
        )
    )


def downgrade() -> None:
    # The removed values were synthetic and should not be recreated.
    pass
