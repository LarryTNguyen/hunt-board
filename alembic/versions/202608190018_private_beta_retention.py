"""apply the private-beta raw payload retention window

Revision ID: 202608190018
Revises: 202608140017
Create Date: 2026-08-19
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision = "202608190018"
down_revision = "202608140017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        op.execute(
            "UPDATE job_versions SET raw_json = '{}'::json, raw_json_expires_at = NULL "
            "WHERE raw_json_expires_at IS NOT NULL"
        )
        op.execute(
            "UPDATE job_postings SET raw_json_expires_at = "
            "LEAST(raw_json_expires_at, CURRENT_TIMESTAMP + INTERVAL '7 days') "
            "WHERE raw_json_expires_at IS NOT NULL"
        )
    else:
        op.execute(
            "UPDATE job_versions SET raw_json = '{}', raw_json_expires_at = NULL "
            "WHERE raw_json_expires_at IS NOT NULL"
        )
        op.execute(
            "UPDATE job_postings SET raw_json_expires_at = "
            "MIN(raw_json_expires_at, datetime('now', '+7 days')) "
            "WHERE raw_json_expires_at IS NOT NULL"
        )


def downgrade() -> None:
    # Purged source payloads cannot be reconstructed. Normalized job and version
    # data is unchanged, so there is no structural downgrade to perform.
    pass
