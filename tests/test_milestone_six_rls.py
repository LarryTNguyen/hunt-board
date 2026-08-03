from __future__ import annotations

import os
import runpy
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError


POSTGRES_URL = os.environ.get("HUNT_BOARD_TEST_POSTGRES_URL")
MIGRATION = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "202607290012_milestone_six.py"
)


def test_rls_migration_covers_every_private_owner_domain() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    namespace = runpy.run_path(str(MIGRATION))
    configured_tables = set(namespace["PRIVATE_DIRECT_TABLES"])
    for table in (
        "user_preferences",
        "saved_searches",
        "saved_jobs",
        "discarded_jobs",
        "user_job_states",
        "job_matches",
        "applications",
        "notifications",
    ):
        assert table in configured_tables
    assert 'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY' in source
    assert "{table}_owner_select" in source
    assert "{table}_owner_update" in source
    assert '"application_events" ENABLE ROW LEVEL SECURITY' in source
    assert "application_events_owner_{suffix}" in source
    assert '("SELECT", "select")' in source
    assert "WITH CHECK" in source
    assert "users.auth_user_id = auth.uid()" in source


@pytest.mark.postgres
@pytest.mark.skipif(
    not POSTGRES_URL,
    reason="set HUNT_BOARD_TEST_POSTGRES_URL for PostgreSQL RLS verification",
)
def test_postgres_rls_isolates_two_users_and_blocks_owner_reassignment() -> None:
    """Exercise policies as a non-owner role; all inserted rows roll back."""
    engine = create_engine(POSTGRES_URL)
    token = uuid4().hex[:10]
    role_name = f"hunt_board_rls_{token}"
    auth_a, auth_b = uuid4(), uuid4()
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            revision = connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
            if revision != "202608030015":
                pytest.skip("PostgreSQL test database is not at Milestone 6.1 head")
            try:
                connection.execute(text(f'CREATE ROLE "{role_name}" NOLOGIN'))
            except DBAPIError:
                transaction.rollback()
                pytest.skip("database user cannot create the non-owner RLS probe role")

            suffix = token
            user_a = connection.scalar(
                text(
                    """
                    INSERT INTO users
                      (auth_user_id, email, normalized_email, role, account_status,
                       is_admin, is_active, preferences_json, created_at, updated_at)
                    VALUES
                      (:auth_id, :email, :email, 'user', 'active', false, true,
                       '{}'::json, now(), now())
                    RETURNING id
                    """
                ),
                {"auth_id": auth_a, "email": f"a-{suffix}@example.com"},
            )
            user_b = connection.scalar(
                text(
                    """
                    INSERT INTO users
                      (auth_user_id, email, normalized_email, role, account_status,
                       is_admin, is_active, preferences_json, created_at, updated_at)
                    VALUES
                      (:auth_id, :email, :email, 'user', 'active', false, true,
                       '{}'::json, now(), now())
                    RETURNING id
                    """
                ),
                {"auth_id": auth_b, "email": f"b-{suffix}@example.com"},
            )
            source_id = connection.scalar(
                text(
                    """
                    INSERT INTO sources
                      (slug, name, ats, company_name, enabled, priority, categories,
                       notes, config_json, health_status, consecutive_failures,
                       close_after_missed_runs, created_at, updated_at)
                    VALUES
                      (:slug, :slug, 'greenhouse', :slug, true, 1, '[]'::json,
                       '', '{}'::json, 'healthy', 0, 12, now(), now())
                    RETURNING id
                    """
                ),
                {"slug": f"rls-{suffix}"},
            )
            job_id = connection.scalar(
                text(
                    """
                    INSERT INTO job_postings
                      (source_id, source_slug, company_name, external_job_id, title,
                       normalized_title, raw_json, locations_json, active,
                       duplicate_status, ranking_score, ranking_reasons,
                       first_seen_at, last_seen_at, consecutive_missed_runs,
                       created_at, updated_at)
                    VALUES
                      (:source_id, :slug, :slug, :external_id, 'RLS Engineer',
                       'rls engineer', '{}'::json, '[]'::json, true, 'unique', 0,
                       '[]'::json, now(), now(), 0, now(), now())
                    RETURNING id
                    """
                ),
                {
                    "source_id": source_id,
                    "slug": f"rls-{suffix}",
                    "external_id": f"rls-{suffix}",
                },
            )
            status_id = connection.scalar(
                text(
                    """
                    INSERT INTO application_statuses
                      (name, slug, sort_order, is_terminal, created_at, updated_at)
                    VALUES (:name, :slug, 999, false, now(), now())
                    RETURNING id
                    """
                ),
                {"name": f"RLS {suffix}", "slug": f"rls-{suffix}"},
            )

            owned_rows: dict[str, tuple[int, int]] = {}
            for table, columns, values in (
                (
                    "user_preferences",
                    "user_id, include_keywords, exclude_keywords, role_groups, "
                    "preferred_levels, preferred_locations, home_location, radius_miles, "
                    "country, remote_allowed, minimum_score_threshold, created_at, updated_at",
                    ":user_id, '[]'::json, '[]'::json, '[]'::json, '[]'::json, "
                    "'[]'::json, 'Remote', 0, 'USA', true, 0, now(), now()",
                ),
                (
                    "saved_searches",
                    "user_id, name, filters_json, sort_by, sort_order, is_default, "
                    "is_active, notify_on_new_matches, created_at, updated_at",
                    ":user_id, :name, '{}'::json, 'ranking_score', 'desc', false, "
                    "true, false, now(), now()",
                ),
                (
                    "user_job_states",
                    "user_id, job_posting_id, saved_at, notes, created_at, updated_at",
                    ":user_id, :job_id, now(), :name, now(), now()",
                ),
                (
                    "job_matches",
                    "user_id, job_posting_id, score, matched, reasons, created_at, updated_at",
                    ":user_id, :job_id, 80, true, '[]'::json, now(), now()",
                ),
                (
                    "notifications",
                    "user_id, job_posting_id, kind, dedupe_key, payload_json, created_at, updated_at",
                    ":user_id, :job_id, 'rls', :name, '{}'::json, now(), now()",
                ),
            ):
                ids = []
                for owner, label in ((user_a, "a"), (user_b, "b")):
                    ids.append(
                        connection.scalar(
                            text(
                                f"INSERT INTO {table} ({columns}) VALUES ({values}) RETURNING id"
                            ),
                            {
                                "user_id": owner,
                                "job_id": job_id,
                                "name": f"{table}-{label}-{suffix}",
                            },
                        )
                    )
                owned_rows[table] = (ids[0], ids[1])

            application_ids = []
            for owner in (user_a, user_b):
                application_ids.append(
                    connection.scalar(
                        text(
                            """
                            INSERT INTO applications
                              (user_id, job_posting_id, status_id, status, notes,
                               created_at, updated_at)
                            VALUES
                              (:user_id, :job_id, :status_id, 'rls', :notes, now(), now())
                            RETURNING id
                            """
                        ),
                        {
                            "user_id": owner,
                            "job_id": job_id,
                            "status_id": status_id,
                            "notes": f"private-{owner}",
                        },
                    )
                )
            for application_id in application_ids:
                connection.execute(
                    text(
                        """
                        INSERT INTO application_events
                          (application_id, status_id, event_type, notes, occurred_at,
                           created_at, updated_at)
                        VALUES
                          (:application_id, :status_id, 'note', 'private event',
                           now(), now(), now())
                        """
                    ),
                    {"application_id": application_id, "status_id": status_id},
                )

            connection.execute(text(f'GRANT USAGE ON SCHEMA public TO "{role_name}"'))
            connection.execute(
                text(f'GRANT SELECT ON users TO "{role_name}"')
            )
            connection.execute(
                text(
                    f'GRANT SELECT, INSERT, UPDATE, DELETE ON '
                    f'user_preferences, saved_searches, user_job_states, job_matches, '
                    f'applications, application_events, notifications TO "{role_name}"'
                )
            )
            connection.execute(text(f'SET LOCAL ROLE "{role_name}"'))
            connection.execute(
                text("SELECT set_config('request.jwt.claim.sub', :subject, true)"),
                {"subject": str(auth_a)},
            )

            for table in (
                "user_preferences",
                "saved_searches",
                "user_job_states",
                "job_matches",
                "applications",
                "application_events",
                "notifications",
            ):
                assert connection.scalar(text(f"SELECT count(*) FROM {table}")) == 1

            savepoint = connection.begin_nested()
            with pytest.raises(DBAPIError):
                connection.execute(
                    text(
                        "UPDATE saved_searches SET user_id = :other "
                        "WHERE id = :owned"
                    ),
                    {
                        "other": user_b,
                        "owned": owned_rows["saved_searches"][0],
                    },
                )
            savepoint.rollback()
        finally:
            if transaction.is_active:
                transaction.rollback()
