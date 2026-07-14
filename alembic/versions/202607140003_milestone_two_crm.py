"""activate milestone two CRM fields

Revision ID: 202607140003
Revises: 202607130002
Create Date: 2026-07-14 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "202607140003"
down_revision = "202607130002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_preferences",
        sa.Column("minimum_score_threshold", sa.Float(), nullable=False, server_default="60"),
    )

    op.alter_column("applications", "status", server_default="applied")
    op.add_column("application_events", sa.Column("old_status", sa.String(120), nullable=True))
    op.add_column("application_events", sa.Column("new_status", sa.String(120), nullable=True))

    op.add_column("notifications", sa.Column("job_posting_id", sa.Integer(), nullable=True))
    op.add_column("notifications", sa.Column("scrape_run_id", sa.Integer(), nullable=True))
    op.add_column("notifications", sa.Column("dedupe_key", sa.String(500), nullable=True))
    op.create_foreign_key(
        "fk_notifications_job_posting_id_job_postings",
        "notifications",
        "job_postings",
        ["job_posting_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_notifications_scrape_run_id_scrape_runs",
        "notifications",
        "scrape_runs",
        ["scrape_run_id"],
        ["id"],
    )
    op.execute("UPDATE notifications SET dedupe_key = 'legacy:' || id WHERE dedupe_key IS NULL")
    op.alter_column("notifications", "dedupe_key", nullable=False)
    op.create_unique_constraint("uq_notifications_dedupe_key", "notifications", ["dedupe_key"])

    # Keep the Milestone 1 status string synchronized where status rows already
    # exist. Fresh databases are seeded after migrations and need no backfill.
    op.execute(
        """
        UPDATE applications
        SET status_id = application_statuses.id,
            status = application_statuses.slug
        FROM application_statuses
        WHERE applications.status_id IS NULL
          AND (
            lower(applications.status) = lower(application_statuses.slug)
            OR lower(applications.status) = lower(application_statuses.name)
          )
        """
    )
    op.execute(
        """
        UPDATE applications
        SET status_id = application_statuses.id,
            status = application_statuses.slug
        FROM application_statuses
        WHERE applications.status_id IS NULL
          AND application_statuses.slug = 'applied'
        """
    )


def downgrade() -> None:
    op.drop_constraint("uq_notifications_dedupe_key", "notifications", type_="unique")
    op.drop_constraint("fk_notifications_scrape_run_id_scrape_runs", "notifications", type_="foreignkey")
    op.drop_constraint("fk_notifications_job_posting_id_job_postings", "notifications", type_="foreignkey")
    op.drop_column("notifications", "dedupe_key")
    op.drop_column("notifications", "scrape_run_id")
    op.drop_column("notifications", "job_posting_id")
    op.drop_column("application_events", "new_status")
    op.drop_column("application_events", "old_status")
    op.alter_column("applications", "status", server_default="saved")
    op.drop_column("user_preferences", "minimum_score_threshold")
