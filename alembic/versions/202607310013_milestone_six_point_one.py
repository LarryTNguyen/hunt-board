"""generalized discovery taxonomy and private tracking

Revision ID: 202607310013
Revises: 202607290012
Create Date: 2026-07-31 12:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from hunt_board.jobs.classification import JOB_FAMILIES


revision = "202607310013"
down_revision = "202607290012"
branch_labels = None
depends_on = None


PREFERENCE_JSON_COLUMNS = (
    "selected_job_families",
    "related_job_families",
    "desired_titles",
    "preferred_countries",
    "excluded_countries",
    "workplace_preferences",
    "employment_types",
    "excluded_companies",
)


def upgrade() -> None:
    op.create_table(
        "job_families",
        sa.Column("slug", sa.String(80), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    family_table = sa.table(
        "job_families",
        sa.column("slug", sa.String),
        sa.column("name", sa.String),
        sa.column("sort_order", sa.Integer),
    )
    op.bulk_insert(
        family_table,
        [{"slug": slug, "name": name, "sort_order": index} for index, (slug, name) in enumerate(JOB_FAMILIES, 1)],
    )

    for column in PREFERENCE_JSON_COLUMNS:
        op.add_column(
            "user_preferences",
            sa.Column(column, sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        )
    op.add_column("user_preferences", sa.Column("sponsorship_required", sa.Boolean(), nullable=True))
    op.add_column("user_preferences", sa.Column("minimum_salary", sa.Numeric(14, 2), nullable=True))

    op.add_column(
        "job_postings",
        sa.Column("job_family_slug", sa.String(80), nullable=False, server_default="other"),
    )
    op.create_foreign_key(
        "fk_job_postings_job_family_slug",
        "job_postings",
        "job_families",
        ["job_family_slug"],
        ["slug"],
    )
    op.add_column("job_postings", sa.Column("classification_confidence", sa.Float(), nullable=False, server_default="0"))
    op.add_column("job_postings", sa.Column("classification_method", sa.String(40), nullable=False, server_default="fallback"))
    op.add_column("job_postings", sa.Column("classification_reason", sa.String(500), nullable=False, server_default="Insufficient evidence"))
    op.add_column("job_postings", sa.Column("classification_overridden_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("job_postings", sa.Column("classification_overridden_by_user_id", sa.Integer(), nullable=True))
    op.add_column("job_postings", sa.Column("classification_override_reason", sa.String(500), nullable=True))
    op.add_column("job_postings", sa.Column("sponsorship_status", sa.String(40), nullable=False, server_default="unknown"))
    op.add_column("job_postings", sa.Column("remote_scope", sa.String(40), nullable=False, server_default="not_remote"))
    op.create_foreign_key(
        "fk_job_postings_classification_override_user",
        "job_postings",
        "users",
        ["classification_overridden_by_user_id"],
        ["id"],
    )
    op.create_index("ix_job_postings_family_active", "job_postings", ["job_family_slug", "active"])

    op.add_column("application_statuses", sa.Column("standard_category", sa.String(40), nullable=False, server_default="applied"))
    op.add_column("application_statuses", sa.Column("user_id", sa.Integer(), nullable=True))
    op.add_column("application_statuses", sa.Column("is_custom", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_foreign_key("fk_application_statuses_user_id", "application_statuses", "users", ["user_id"], ["id"])
    bind = op.get_bind()
    for constraint in sa.inspect(bind).get_unique_constraints("application_statuses"):
        if constraint.get("name") and constraint.get("column_names") in (["name"], ["slug"]):
            op.drop_constraint(constraint["name"], "application_statuses", type_="unique")
    op.create_unique_constraint("uq_application_statuses_user_slug", "application_statuses", ["user_id", "slug"])
    category_by_slug = {
        "nothing": "archived",
        "applied": "applied",
        "oa-received": "interview",
        "interview-scheduled": "interview",
        "positive-hear-back": "interview",
        "ghosted": "archived",
        "rejection": "rejected",
        "offer-received": "offer",
        "withdrawn": "withdrawn",
    }
    for slug, category in category_by_slug.items():
        bind.execute(
            sa.text("UPDATE application_statuses SET standard_category=:category WHERE slug=:slug"),
            {"slug": slug, "category": category},
        )

    op.create_table(
        "manual_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("location", sa.String(500), nullable=True),
        sa.Column("workplace_type", sa.String(120), nullable=True),
        sa.Column("job_family_slug", sa.String(80), sa.ForeignKey("job_families.slug"), nullable=False, server_default="other"),
        sa.Column("posting_url", sa.String(1000), nullable=True),
        sa.Column("apply_url", sa.String(1000), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("approval_status", sa.String(40), nullable=False, server_default="private"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_manual_jobs_user_created", "manual_jobs", ["user_id", "created_at"])

    op.add_column("applications", sa.Column("manual_job_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_applications_manual_job_id", "applications", "manual_jobs", ["manual_job_id"], ["id"])
    op.add_column("applications", sa.Column("link_url", sa.String(1000), nullable=True))
    op.add_column("applications", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("applications", sa.Column("purge_after", sa.DateTime(timezone=True), nullable=True))
    op.alter_column("applications", "job_posting_id", existing_type=sa.Integer(), nullable=True)
    op.create_index("ix_applications_user_deleted", "applications", ["user_id", "deleted_at"])

    if bind.dialect.name == "postgresql":
        _enable_private_rls()


def _enable_private_rls() -> None:
    op.execute('ALTER TABLE "manual_jobs" ENABLE ROW LEVEL SECURITY')
    for action, suffix in (("SELECT", "select"), ("INSERT", "insert"), ("UPDATE", "update"), ("DELETE", "delete")):
        predicate = """
          EXISTS (SELECT 1 FROM users
                  WHERE users.id = manual_jobs.user_id
                    AND users.auth_user_id = auth.uid()
                    AND users.is_active AND users.account_status = 'active')
        """
        clause = f"FOR INSERT WITH CHECK ({predicate})" if action == "INSERT" else (
            f"FOR UPDATE USING ({predicate}) WITH CHECK ({predicate})" if action == "UPDATE" else f"FOR {action} USING ({predicate})"
        )
        op.execute(f"CREATE POLICY manual_jobs_owner_{suffix} ON manual_jobs {clause}")
    op.execute('ALTER TABLE "application_statuses" ENABLE ROW LEVEL SECURITY')
    op.execute("CREATE POLICY application_statuses_visible ON application_statuses FOR SELECT USING (user_id IS NULL OR EXISTS (SELECT 1 FROM users WHERE users.id=application_statuses.user_id AND users.auth_user_id=auth.uid()))")
    for action, suffix in (("INSERT", "insert"), ("UPDATE", "update"), ("DELETE", "delete")):
        predicate = "application_statuses.is_custom AND EXISTS (SELECT 1 FROM users WHERE users.id=application_statuses.user_id AND users.auth_user_id=auth.uid() AND users.is_active)"
        clause = f"FOR INSERT WITH CHECK ({predicate})" if action == "INSERT" else (
            f"FOR UPDATE USING ({predicate}) WITH CHECK ({predicate})" if action == "UPDATE" else f"FOR DELETE USING ({predicate})"
        )
        op.execute(f"CREATE POLICY application_statuses_owner_{suffix} ON application_statuses {clause}")
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE ON manual_jobs, application_statuses TO authenticated;
            GRANT USAGE, SELECT ON SEQUENCE manual_jobs_id_seq, application_statuses_id_seq TO authenticated;
          END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table in ("manual_jobs", "application_statuses"):
            policies = list(bind.execute(sa.text("SELECT policyname FROM pg_policies WHERE schemaname=current_schema() AND tablename=:table"), {"table": table}).scalars())
            for policy in policies:
                op.execute(f'DROP POLICY IF EXISTS "{policy}" ON "{table}"')
            op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
    op.drop_index("ix_applications_user_deleted", table_name="applications")
    op.alter_column("applications", "job_posting_id", existing_type=sa.Integer(), nullable=False)
    for column in ("purge_after", "deleted_at", "link_url"):
        op.drop_column("applications", column)
    op.drop_constraint("fk_applications_manual_job_id", "applications", type_="foreignkey")
    op.drop_column("applications", "manual_job_id")
    op.drop_index("ix_manual_jobs_user_created", table_name="manual_jobs")
    op.drop_table("manual_jobs")
    op.execute("DELETE FROM application_statuses WHERE is_custom")
    op.drop_constraint("uq_application_statuses_user_slug", "application_statuses", type_="unique")
    op.drop_constraint("fk_application_statuses_user_id", "application_statuses", type_="foreignkey")
    for column in ("is_custom", "user_id", "standard_category"):
        op.drop_column("application_statuses", column)
    op.create_unique_constraint("uq_application_statuses_name", "application_statuses", ["name"])
    op.create_unique_constraint("uq_application_statuses_slug", "application_statuses", ["slug"])
    op.drop_index("ix_job_postings_family_active", table_name="job_postings")
    op.drop_constraint("fk_job_postings_classification_override_user", "job_postings", type_="foreignkey")
    op.drop_constraint("fk_job_postings_job_family_slug", "job_postings", type_="foreignkey")
    for column in (
        "remote_scope", "sponsorship_status", "classification_override_reason", "classification_overridden_by_user_id", "classification_overridden_at",
        "classification_reason", "classification_method", "classification_confidence", "job_family_slug",
    ):
        op.drop_column("job_postings", column)
    op.drop_column("user_preferences", "minimum_salary")
    op.drop_column("user_preferences", "sponsorship_required")
    for column in reversed(PREFERENCE_JSON_COLUMNS):
        op.drop_column("user_preferences", column)
    op.drop_table("job_families")
