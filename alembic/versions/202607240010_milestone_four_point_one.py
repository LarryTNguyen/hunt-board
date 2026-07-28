"""add canonical structured job locations

Revision ID: 202607240010
Revises: 202607220009
Create Date: 2026-07-24 12:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "202607240010"
down_revision = "202607220009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "job_postings",
        sa.Column("locations_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            UPDATE job_postings
            SET locations_json = json_build_array(
                json_build_object(
                    'display', location,
                    'country_code', location_country_code,
                    'country', location_country,
                    'is_primary', true
                )
            )
            WHERE location IS NOT NULL AND btrim(location) <> ''
            """
        )
    elif bind.dialect.name == "sqlite":
        op.execute(
            """
            UPDATE job_postings
            SET locations_json = json_array(
                json_object(
                    'display', location,
                    'country_code', location_country_code,
                    'country', location_country,
                    'is_primary', 1
                )
            )
            WHERE location IS NOT NULL AND trim(location) <> ''
            """
        )
def downgrade() -> None:
    op.drop_column("job_postings", "locations_json")
