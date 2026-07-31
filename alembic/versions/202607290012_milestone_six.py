"""add multi-user identity, invitations, job state, and RLS

Revision ID: 202607290012
Revises: 202607270011
Create Date: 2026-07-29 12:00:00.000000
"""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa
from alembic import op


revision = "202607290012"
down_revision = "202607270011"
branch_labels = None
depends_on = None


PRIVATE_DIRECT_TABLES = (
    "user_preferences",
    "saved_searches",
    "saved_jobs",
    "discarded_jobs",
    "user_job_states",
    "job_matches",
    "applications",
    "notifications",
)


def _drop_constraint_if_present(table: str, name: str, constraint_type: str) -> None:
    bind = op.get_bind()
    names = {
        item["name"]
        for item in sa.inspect(bind).get_unique_constraints(table)
        if item.get("name")
    }
    if name in names:
        op.drop_constraint(name, table, type_=constraint_type)


def _create_auth_uid_helper() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS auth")
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1
            FROM pg_proc p
            JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname = 'auth' AND p.proname = 'uid'
          ) THEN
            EXECUTE $function$
              CREATE FUNCTION auth.uid() RETURNS uuid
              LANGUAGE sql STABLE
              AS 'SELECT NULLIF(current_setting(''request.jwt.claim.sub'', true), '''')::uuid'
            $function$;
          END IF;
        END
        $$;
        """
    )


def _enable_rls() -> None:
    _create_auth_uid_helper()
    for table in PRIVATE_DIRECT_TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(
            f"""
            CREATE POLICY {table}_owner_select ON "{table}"
            FOR SELECT USING (
              EXISTS (
                SELECT 1 FROM users
                WHERE users.id = "{table}".user_id
                  AND users.auth_user_id = auth.uid()
                  AND users.is_active
                  AND users.account_status = 'active'
              )
            )
            """
        )
        op.execute(
            f"""
            CREATE POLICY {table}_owner_insert ON "{table}"
            FOR INSERT WITH CHECK (
              EXISTS (
                SELECT 1 FROM users
                WHERE users.id = "{table}".user_id
                  AND users.auth_user_id = auth.uid()
                  AND users.is_active
                  AND users.account_status = 'active'
              )
            )
            """
        )
        op.execute(
            f"""
            CREATE POLICY {table}_owner_update ON "{table}"
            FOR UPDATE
            USING (
              EXISTS (
                SELECT 1 FROM users
                WHERE users.id = "{table}".user_id
                  AND users.auth_user_id = auth.uid()
                  AND users.is_active
                  AND users.account_status = 'active'
              )
            )
            WITH CHECK (
              EXISTS (
                SELECT 1 FROM users
                WHERE users.id = "{table}".user_id
                  AND users.auth_user_id = auth.uid()
                  AND users.is_active
                  AND users.account_status = 'active'
              )
            )
            """
        )
        op.execute(
            f"""
            CREATE POLICY {table}_owner_delete ON "{table}"
            FOR DELETE USING (
              EXISTS (
                SELECT 1 FROM users
                WHERE users.id = "{table}".user_id
                  AND users.auth_user_id = auth.uid()
                  AND users.is_active
                  AND users.account_status = 'active'
              )
            )
            """
        )

    op.execute('ALTER TABLE "application_events" ENABLE ROW LEVEL SECURITY')
    for action, suffix in (
        ("SELECT", "select"),
        ("INSERT", "insert"),
        ("UPDATE", "update"),
        ("DELETE", "delete"),
    ):
        predicate = """
          EXISTS (
            SELECT 1
            FROM applications
            JOIN users ON users.id = applications.user_id
            WHERE applications.id = application_events.application_id
              AND users.auth_user_id = auth.uid()
              AND users.is_active
              AND users.account_status = 'active'
          )
        """
        if action == "INSERT":
            clause = f"FOR INSERT WITH CHECK ({predicate})"
        elif action == "UPDATE":
            clause = f"FOR UPDATE USING ({predicate}) WITH CHECK ({predicate})"
        else:
            clause = f"FOR {action} USING ({predicate})"
        op.execute(
            f"CREATE POLICY application_events_owner_{suffix} "
            f'ON "application_events" {clause}'
        )

    op.execute('ALTER TABLE "users" ENABLE ROW LEVEL SECURITY')
    op.execute(
        """
        CREATE POLICY users_self_select ON users
        FOR SELECT USING (auth_user_id = auth.uid())
        """
    )
    op.execute(
        """
        DO $$
        DECLARE role_name text;
        BEGIN
          FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated']
          LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
              EXECUTE format(
                'REVOKE ALL ON sources, job_postings, job_versions, scrape_runs, '
                'scrape_source_runs, duplicate_reviews, invitations, audit_events FROM %I',
                role_name
              );
            END IF;
          END LOOP;
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
            EXECUTE 'GRANT SELECT ON users TO authenticated';
            EXECUTE
              'GRANT SELECT, INSERT, UPDATE, DELETE ON '
              'user_preferences, saved_searches, saved_jobs, discarded_jobs, '
              'user_job_states, job_matches, applications, application_events, '
              'notifications TO authenticated';
          END IF;
        END
        $$;
        """
    )


def _disable_rls() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for table in (*PRIVATE_DIRECT_TABLES, "application_events"):
        policies = list(bind.execute(
            sa.text(
                "SELECT policyname FROM pg_policies "
                "WHERE schemaname = current_schema() AND tablename = :table"
            ),
            {"table": table},
        ).scalars())
        for policy in policies:
            op.execute(f'DROP POLICY IF EXISTS "{policy}" ON "{table}"')
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
    op.execute("DROP POLICY IF EXISTS users_self_select ON users")
    op.execute("ALTER TABLE users DISABLE ROW LEVEL SECURITY")


def upgrade() -> None:
    auth_uuid_type = sa.Uuid()
    op.add_column("users", sa.Column("auth_user_id", auth_uuid_type, nullable=True))
    op.add_column("users", sa.Column("normalized_email", sa.String(320), nullable=True))
    op.add_column("users", sa.Column("first_name", sa.String(120), nullable=True))
    op.add_column("users", sa.Column("last_name", sa.String(120), nullable=True))
    op.add_column("users", sa.Column("display_name", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("role", sa.String(20), nullable=False, server_default="user"))
    op.add_column(
        "users",
        sa.Column("account_status", sa.String(40), nullable=False, server_default="active"),
    )
    op.add_column("users", sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "users", sa.Column("deletion_scheduled_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("users", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "users", sa.Column("onboarding_completed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "users", sa.Column("onboarding_skipped_at", sa.DateTime(timezone=True), nullable=True)
    )

    bind = op.get_bind()
    for row in bind.execute(sa.text("SELECT id, email, is_admin, is_active FROM users")).mappings():
        normalized = row["email"].strip().lower()
        seed_uuid = uuid5(NAMESPACE_URL, f"hunt-board:local-seed:{normalized}")
        bind.execute(
            sa.text(
                """
                UPDATE users
                SET auth_user_id = :auth_user_id,
                    normalized_email = :normalized_email,
                    role = :role,
                    account_status = :account_status
                WHERE id = :id
                """
            ),
            {
                "auth_user_id": seed_uuid,
                "normalized_email": normalized,
                "role": "admin" if row["is_admin"] else "user",
                "account_status": "active" if row["is_active"] else "deactivated",
                "id": row["id"],
            },
        )
    op.alter_column("users", "auth_user_id", nullable=False)
    op.alter_column("users", "normalized_email", nullable=False)
    op.create_unique_constraint("uq_users_auth_user_id", "users", ["auth_user_id"])
    op.create_unique_constraint("uq_users_normalized_email", "users", ["normalized_email"])

    op.create_table(
        "invitations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("normalized_email", sa.String(320), nullable=False),
        sa.Column("inviter_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="pending"),
        sa.Column("accepted_auth_user_id", auth_uuid_type, nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_invitations_email_status", "invitations", ["normalized_email", "status"]
    )
    op.execute(
        """
        INSERT INTO invitations
          (normalized_email, inviter_user_id, status, accepted_auth_user_id,
           accepted_at, created_at, updated_at)
        SELECT normalized_email, id, 'accepted', auth_user_id,
               CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM users
        """
    )

    op.create_table(
        "user_job_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("job_posting_id", sa.Integer(), sa.ForeignKey("job_postings.id"), nullable=False),
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "job_posting_id", name="uq_user_job_states_user_job"),
    )
    op.create_index("ix_user_job_states_user_saved", "user_job_states", ["user_id", "saved_at"])
    op.create_index(
        "ix_user_job_states_user_dismissed", "user_job_states", ["user_id", "dismissed_at"]
    )
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            INSERT INTO user_job_states
              (user_id, job_posting_id, saved_at, notes, created_at, updated_at)
            SELECT user_id, job_posting_id, created_at, notes, created_at, updated_at
            FROM saved_jobs
            ON CONFLICT (user_id, job_posting_id)
            DO UPDATE SET saved_at = EXCLUDED.saved_at, notes = EXCLUDED.notes
            """
        )
        op.execute(
            """
            INSERT INTO user_job_states
              (user_id, job_posting_id, dismissed_at, created_at, updated_at)
            SELECT user_id, job_posting_id, created_at, created_at, updated_at
            FROM discarded_jobs
            ON CONFLICT (user_id, job_posting_id)
            DO UPDATE SET dismissed_at = EXCLUDED.dismissed_at
            """
        )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_name", sa.String(120), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("target_type", sa.String(80), nullable=True),
        sa.Column("target_id", sa.String(255), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("details_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_audit_events_event_created", "audit_events", ["event_name", "created_at"]
    )

    _drop_constraint_if_present("applications", "uq_applications_user_job", "unique")
    _drop_constraint_if_present("notifications", "uq_notifications_dedupe_key", "unique")
    op.create_unique_constraint(
        "uq_notifications_user_dedupe_key", "notifications", ["user_id", "dedupe_key"]
    )

    if bind.dialect.name == "postgresql":
        _enable_rls()


def downgrade() -> None:
    bind = op.get_bind()
    _disable_rls()
    _drop_constraint_if_present(
        "notifications", "uq_notifications_user_dedupe_key", "unique"
    )
    op.create_unique_constraint(
        "uq_notifications_dedupe_key", "notifications", ["dedupe_key"]
    )
    op.create_unique_constraint(
        "uq_applications_user_job", "applications", ["user_id", "job_posting_id"]
    )
    op.drop_index("ix_audit_events_event_created", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_user_job_states_user_dismissed", table_name="user_job_states")
    op.drop_index("ix_user_job_states_user_saved", table_name="user_job_states")
    op.drop_table("user_job_states")
    op.drop_index("ix_invitations_email_status", table_name="invitations")
    op.drop_table("invitations")
    op.drop_constraint("uq_users_normalized_email", "users", type_="unique")
    op.drop_constraint("uq_users_auth_user_id", "users", type_="unique")
    for column in (
        "onboarding_skipped_at",
        "onboarding_completed_at",
        "deleted_at",
        "deletion_scheduled_at",
        "deactivated_at",
        "account_status",
        "role",
        "display_name",
        "last_name",
        "first_name",
        "normalized_email",
        "auth_user_id",
    ):
        op.drop_column("users", column)
