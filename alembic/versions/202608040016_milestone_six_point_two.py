"""production operations, queue, quarantine, and lifecycle history

Revision ID: 202608040016
Revises: 202608030015
Create Date: 2026-08-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision = "202608040016"
down_revision = "202608030015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("last_successful_job_count", sa.Integer(), nullable=True))
    op.add_column("sources", sa.Column("quarantine_count", sa.Integer(), server_default="0", nullable=False))

    for name, column in (
        ("request_id", sa.Column("request_id", sa.String(64), nullable=True)),
        ("trace_id", sa.Column("trace_id", sa.String(64), nullable=True)),
        ("environment", sa.Column("environment", sa.String(24), server_default="development", nullable=False)),
        ("release", sa.Column("release", sa.String(120), server_default="development", nullable=False)),
        ("coalesced_triggers", sa.Column("coalesced_triggers", sa.Integer(), server_default="0", nullable=False)),
        ("cancel_requested_at", sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True)),
        ("cancelled_at", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True)),
    ):
        op.add_column("scrape_runs", column)
    op.add_column(
        "scrape_runs",
        sa.Column("total_reactivated_jobs", sa.Integer(), server_default="0", nullable=False),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.create_index(
            "uq_scrape_runs_single_pending",
            "scrape_runs",
            ["status"],
            unique=True,
            postgresql_where=sa.text("status = 'pending'"),
        )
    else:
        op.create_index("ix_scrape_runs_queue_status", "scrape_runs", ["status"], unique=False)

    for column in (
        sa.Column("reactivated_jobs", sa.Integer(), server_default="0", nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("timeout_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("parser_failure_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("quarantine_status", sa.String(40), nullable=True),
        sa.Column("trace_id", sa.String(64), nullable=True),
    ):
        op.add_column("scrape_source_runs", column)

    op.create_table(
        "ingestion_quarantines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scrape_run_id", sa.Integer(), sa.ForeignKey("scrape_runs.id"), nullable=False),
        sa.Column("scrape_source_run_id", sa.Integer(), sa.ForeignKey("scrape_source_runs.id"), nullable=False),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("source_slug", sa.String(120), nullable=False),
        sa.Column("status", sa.String(40), server_default="pending", nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("diff_summary", sa.JSON(), nullable=False),
        sa.Column("observed_external_ids", sa.JSON(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decision_note", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_ingestion_quarantines_status_created",
        "ingestion_quarantines",
        ["status", "created_at"],
    )
    op.create_table(
        "job_lifecycle_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_posting_id", sa.Integer(), sa.ForeignKey("job_postings.id"), nullable=False),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("scrape_run_id", sa.Integer(), sa.ForeignKey("scrape_runs.id"), nullable=True),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("reason", sa.String(255), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_job_lifecycle_job_occurred",
        "job_lifecycle_events",
        ["job_posting_id", "occurred_at"],
    )

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            DO $$
            DECLARE role_name text;
            BEGIN
              FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated'] LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
                  EXECUTE format(
                    'REVOKE ALL ON ingestion_quarantines, job_lifecycle_events FROM %I',
                    role_name
                  );
                END IF;
              END LOOP;
            END $$;
            """
        )


def downgrade() -> None:
    op.drop_index("ix_job_lifecycle_job_occurred", table_name="job_lifecycle_events")
    op.drop_table("job_lifecycle_events")
    op.drop_index("ix_ingestion_quarantines_status_created", table_name="ingestion_quarantines")
    op.drop_table("ingestion_quarantines")
    for name in ("trace_id", "quarantine_status", "parser_failure_count", "timeout_count", "retry_count", "reactivated_jobs"):
        op.drop_column("scrape_source_runs", name)
    if op.get_bind().dialect.name == "postgresql":
        op.drop_index("uq_scrape_runs_single_pending", table_name="scrape_runs")
    else:
        op.drop_index("ix_scrape_runs_queue_status", table_name="scrape_runs")
    for name in (
        "total_reactivated_jobs", "cancelled_at", "cancel_requested_at", "coalesced_triggers", "release",
        "environment", "trace_id", "request_id",
    ):
        op.drop_column("scrape_runs", name)
    op.drop_column("sources", "quarantine_count")
    op.drop_column("sources", "last_successful_job_count")
