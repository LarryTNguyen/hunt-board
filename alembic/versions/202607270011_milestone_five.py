"""add saved searches for the daily hunt

Revision ID: 202607270011
Revises: 202607240010
Create Date: 2026-07-27 12:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "202607270011"
down_revision = "202607240010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "saved_searches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("filters_json", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("sort_by", sa.String(length=40), server_default="ranking_score", nullable=False),
        sa.Column("sort_order", sa.String(length=4), server_default="desc", nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("notify_on_new_matches", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("last_viewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_saved_searches_user_name"),
    )
    op.create_index(
        "ix_saved_searches_user_active",
        "saved_searches",
        ["user_id", "is_active"],
        unique=False,
    )
    op.create_index(
        "ix_saved_searches_user_last_viewed",
        "saved_searches",
        ["user_id", "last_viewed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_saved_searches_user_last_viewed", table_name="saved_searches")
    op.drop_index("ix_saved_searches_user_active", table_name="saved_searches")
    op.drop_table("saved_searches")
