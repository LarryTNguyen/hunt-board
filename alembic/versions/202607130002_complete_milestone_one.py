"""complete milestone one schema

Revision ID: 202607130002
Revises: 202607100001
Create Date: 2026-07-13 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "202607130002"
down_revision = "202607100001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("users", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_table(
        "user_preferences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, unique=True),
        sa.Column("include_keywords", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("exclude_keywords", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("role_groups", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("preferred_levels", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("preferred_locations", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("home_location", sa.String(255), nullable=False, server_default="San Jose"),
        sa.Column("radius_miles", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("country", sa.String(120), nullable=False, server_default="USA"),
        sa.Column("remote_allowed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.add_column("sources", sa.Column("careers_url", sa.String(1000), nullable=True))
    op.add_column("sources", sa.Column("categories", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")))
    op.add_column("sources", sa.Column("notes", sa.Text(), nullable=False, server_default=""))
    op.add_column("sources", sa.Column("health_status", sa.String(40), nullable=False, server_default="unknown"))
    op.add_column("sources", sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("sources", sa.Column("last_successful_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sources", sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=True))

    op.alter_column("job_postings", "external_job_id", existing_type=sa.String(255), nullable=True)
    op.add_column("job_postings", sa.Column("posting_url", sa.String(1000), nullable=True))
    op.add_column("job_postings", sa.Column("raw_json_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("job_postings", sa.Column("description_hash", sa.String(64), nullable=True))
    op.add_column("job_postings", sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("job_postings", sa.Column("consecutive_missed_runs", sa.Integer(), nullable=False, server_default="0"))
    op.create_table(
        "job_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_posting_id", sa.Integer(), sa.ForeignKey("job_postings.id"), nullable=False),
        sa.Column("description_hash", sa.String(64), nullable=False),
        sa.Column("description_html", sa.Text(), nullable=True),
        sa.Column("description_text", sa.Text(), nullable=True),
        sa.Column("raw_json", sa.JSON(), nullable=False),
        sa.Column("raw_json_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("job_posting_id", "description_hash", name="uq_job_versions_job_hash"),
    )
    op.create_table(
        "job_matches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("job_posting_id", sa.Integer(), sa.ForeignKey("job_postings.id"), nullable=False),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("matched", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("reasons", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "job_posting_id", name="uq_job_matches_user_job"),
    )
    op.create_table(
        "saved_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("job_posting_id", sa.Integer(), sa.ForeignKey("job_postings.id"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "job_posting_id", name="uq_saved_jobs_user_job"),
    )
    op.create_table(
        "application_statuses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("slug", sa.String(120), nullable=False, unique=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_terminal", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.add_column("applications", sa.Column("status_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_applications_status_id_application_statuses", "applications", "application_statuses", ["status_id"], ["id"]
    )
    op.create_table(
        "application_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("application_id", sa.Integer(), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("status_id", sa.Integer(), sa.ForeignKey("application_statuses.id"), nullable=True),
        sa.Column("event_type", sa.String(80), nullable=False, server_default="status_changed"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(80), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.add_column("duplicate_reviews", sa.Column("resolution_notes", sa.Text(), nullable=True))
    op.add_column("duplicate_reviews", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))

    op.add_column("scrape_runs", sa.Column("triggered_by", sa.String(80), nullable=False, server_default="api"))
    op.add_column("scrape_runs", sa.Column("total_sources_checked", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("scrape_runs", sa.Column("total_jobs_seen", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("scrape_runs", sa.Column("total_new_jobs", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("scrape_runs", sa.Column("total_updated_jobs", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("scrape_runs", sa.Column("total_closed_jobs", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("scrape_runs", sa.Column("total_duplicates", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("scrape_runs", sa.Column("duration_ms", sa.Integer(), nullable=True))

    op.add_column("scrape_source_runs", sa.Column("jobs_seen", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("scrape_source_runs", sa.Column("new_jobs", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("scrape_source_runs", sa.Column("updated_jobs", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("scrape_source_runs", sa.Column("closed_jobs", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("scrape_source_runs", sa.Column("duplicates_found", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("scrape_source_runs", sa.Column("duration_ms", sa.Integer(), nullable=True))


def downgrade() -> None:
    for column in ("duration_ms", "duplicates_found", "closed_jobs", "updated_jobs", "new_jobs", "jobs_seen"):
        op.drop_column("scrape_source_runs", column)
    for column in (
        "duration_ms", "total_duplicates", "total_closed_jobs", "total_updated_jobs", "total_new_jobs",
        "total_jobs_seen", "total_sources_checked", "triggered_by",
    ):
        op.drop_column("scrape_runs", column)
    op.drop_column("duplicate_reviews", "resolved_at")
    op.drop_column("duplicate_reviews", "resolution_notes")
    op.drop_table("notifications")
    op.drop_table("application_events")
    op.drop_constraint("fk_applications_status_id_application_statuses", "applications", type_="foreignkey")
    op.drop_column("applications", "status_id")
    op.drop_table("application_statuses")
    op.drop_table("saved_jobs")
    op.drop_table("job_matches")
    op.drop_table("job_versions")
    op.drop_column("job_postings", "consecutive_missed_runs")
    op.drop_column("job_postings", "description_hash")
    op.drop_column("job_postings", "source_updated_at")
    op.drop_column("job_postings", "raw_json_expires_at")
    op.drop_column("job_postings", "posting_url")
    op.alter_column("job_postings", "external_job_id", existing_type=sa.String(255), nullable=False)
    for column in (
        "next_due_at", "last_successful_at", "consecutive_failures", "health_status", "notes", "categories", "careers_url",
    ):
        op.drop_column("sources", column)
    op.drop_table("user_preferences")
    op.drop_column("users", "is_active")
    op.drop_column("users", "is_admin")
