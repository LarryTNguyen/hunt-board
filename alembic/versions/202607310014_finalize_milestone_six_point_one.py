"""finalize per-user custom stage uniqueness

Revision ID: 202607310014
Revises: 202607310013
Create Date: 2026-07-31 18:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "202607310014"
down_revision = "202607310013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    for constraint in sa.inspect(bind).get_unique_constraints("application_statuses"):
        if constraint.get("name") and constraint.get("column_names") in (["name"], ["slug"]):
            op.drop_constraint(constraint["name"], "application_statuses", type_="unique")
    if bind.dialect.name == "postgresql":
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
    # Restoring global uniqueness would reject valid same-name stages belonging
    # to different users, so the compatibility revision is intentionally a no-op.
    pass
