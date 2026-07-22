"""backfill conservative country values for existing postings

Revision ID: 202607210007
Revises: 202607210006
Create Date: 2026-07-21 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "202607210007"
down_revision = "202607210006"
branch_labels = None
depends_on = None


COUNTRY_BACKFILLS = (
    (
        "US",
        "United States",
        ("%united states%", "%san francisco%", "%los angeles%", "%california%"),
    ),
    ("CA", "Canada", ("%canada%",)),
    ("GB", "United Kingdom", ("%united kingdom%",)),
    ("IN", "India", ("%india%",)),
)


def upgrade() -> None:
    connection = op.get_bind()
    for code, name, patterns in COUNTRY_BACKFILLS:
        conditions = " OR ".join(f"lower(location) LIKE :pattern_{index}" for index in range(len(patterns)))
        parameters = {f"pattern_{index}": pattern for index, pattern in enumerate(patterns)}
        parameters.update({"code": code, "name": name})
        connection.execute(
            sa.text(
                f"""
                UPDATE job_postings
                SET location_country_code = :code, location_country = :name
                WHERE location_country_code IS NULL
                  AND location IS NOT NULL
                  AND ({conditions})
                """
            ),
            parameters,
        )


def downgrade() -> None:
    # Ingestion owns these normalized values after backfill; a downgrade must not
    # erase countries that may have been refreshed from explicit ATS fields.
    pass
