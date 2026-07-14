"""initial schema

Revision ID: 202607100001
Revises:
Create Date: 2026-07-10 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "202607100001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("preferences_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("ats", sa.String(length=40), nullable=False),
        sa.Column("company_name", sa.String(length=255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("config_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("slug", name="uq_sources_slug"),
    )
    op.create_table(
        "scrape_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sources_requested", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("total_fetched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_upserted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_closed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_errors", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "job_postings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("source_slug", sa.String(length=120), nullable=False),
        sa.Column("company_name", sa.String(length=255), nullable=False),
        sa.Column("external_job_id", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("normalized_title", sa.String(length=500), nullable=False),
        sa.Column("location", sa.String(length=500), nullable=True),
        sa.Column("normalized_location", sa.String(length=500), nullable=True),
        sa.Column("department", sa.String(length=255), nullable=True),
        sa.Column("employment_type", sa.String(length=120), nullable=True),
        sa.Column("workplace_type", sa.String(length=120), nullable=True),
        sa.Column("apply_url", sa.String(length=1000), nullable=True),
        sa.Column("canonical_apply_url", sa.String(length=1000), nullable=True),
        sa.Column("description_html", sa.Text(), nullable=True),
        sa.Column("description_text", sa.Text(), nullable=True),
        sa.Column("raw_json", sa.JSON(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("duplicate_status", sa.String(length=40), nullable=False, server_default="unique"),
        sa.Column("duplicate_of_job_id", sa.Integer(), sa.ForeignKey("job_postings.id"), nullable=True),
        sa.Column("ranking_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("ranking_reasons", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reposted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("source_id", "external_job_id", name="uq_job_postings_source_external_id"),
    )
    op.create_index("ix_job_postings_active", "job_postings", ["active"])
    op.create_index("ix_job_postings_canonical_apply_url", "job_postings", ["canonical_apply_url"])
    op.create_index(
        "ix_job_postings_company_title_location",
        "job_postings",
        ["company_name", "normalized_title", "normalized_location"],
    )
    op.create_table(
        "applications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("job_posting_id", sa.Integer(), sa.ForeignKey("job_postings.id"), nullable=False),
        sa.Column("status", sa.String(length=80), nullable=False, server_default="saved"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "job_posting_id", name="uq_applications_user_job"),
    )
    op.create_table(
        "duplicate_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("candidate_job_id", sa.Integer(), sa.ForeignKey("job_postings.id"), nullable=False),
        sa.Column("existing_job_id", sa.Integer(), sa.ForeignKey("job_postings.id"), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="open"),
        sa.Column("signals_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "scrape_source_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scrape_run_id", sa.Integer(), sa.ForeignKey("scrape_runs.id"), nullable=False),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id"), nullable=True),
        sa.Column("source_slug", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("fetched_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("upserted_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("closed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("scrape_source_runs")
    op.drop_table("duplicate_reviews")
    op.drop_table("applications")
    op.drop_index("ix_job_postings_company_title_location", table_name="job_postings")
    op.drop_index("ix_job_postings_canonical_apply_url", table_name="job_postings")
    op.drop_index("ix_job_postings_active", table_name="job_postings")
    op.drop_table("job_postings")
    op.drop_table("scrape_runs")
    op.drop_table("sources")
    op.drop_table("users")

