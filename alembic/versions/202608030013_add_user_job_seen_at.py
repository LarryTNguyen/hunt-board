"""Add per-user job seen state.

Revision ID: 202608030013
Revises: 202607290012
Create Date: 2026-08-03 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "202608030013"
down_revision = "202607290012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_job_states",
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_user_job_states_user_seen",
        "user_job_states",
        ["user_id", "seen_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_job_states_user_seen", table_name="user_job_states")
    op.drop_column("user_job_states", "seen_at")
