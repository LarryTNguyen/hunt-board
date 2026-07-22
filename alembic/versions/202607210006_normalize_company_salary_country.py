"""normalize company logos, salary ranges, and location countries

Revision ID: 202607210006
Revises: 202607150005
Create Date: 2026-07-21 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "202607210006"
down_revision = "202607150005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("company_logo_url", sa.String(length=1000), nullable=True))
    op.add_column("job_postings", sa.Column("location_country_code", sa.String(length=2), nullable=True))
    op.add_column("job_postings", sa.Column("location_country", sa.String(length=120), nullable=True))
    op.add_column("job_postings", sa.Column("salary_min", sa.Numeric(precision=14, scale=2), nullable=True))
    op.add_column("job_postings", sa.Column("salary_max", sa.Numeric(precision=14, scale=2), nullable=True))
    op.add_column("job_postings", sa.Column("salary_currency", sa.String(length=3), nullable=True))
    op.add_column("job_postings", sa.Column("salary_interval", sa.String(length=40), nullable=True))
    op.create_index("ix_job_postings_location_country_code", "job_postings", ["location_country_code"])


def downgrade() -> None:
    op.drop_index("ix_job_postings_location_country_code", table_name="job_postings")
    op.drop_column("job_postings", "salary_interval")
    op.drop_column("job_postings", "salary_currency")
    op.drop_column("job_postings", "salary_max")
    op.drop_column("job_postings", "salary_min")
    op.drop_column("job_postings", "location_country")
    op.drop_column("job_postings", "location_country_code")
    op.drop_column("sources", "company_logo_url")
