"""add per-user discarded jobs

Revision ID: 202607150005
Revises: 202607140004
Create Date: 2026-07-15 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "202607150005"
down_revision = "202607140004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discarded_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("job_posting_id", sa.Integer(), sa.ForeignKey("job_postings.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "job_posting_id", name="uq_discarded_jobs_user_job"),
    )
    op.create_index("ix_discarded_jobs_user_created", "discarded_jobs", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_discarded_jobs_user_created", table_name="discarded_jobs")
    op.drop_table("discarded_jobs")
