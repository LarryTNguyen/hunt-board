"""seed production-safe application status reference data

Revision ID: 202608140017
Revises: 202608040016
Create Date: 2026-08-14
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op


revision = "202608140017"
down_revision = "202608040016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


DEFAULT_APPLICATION_STATUSES = (
    ("Nothing", "nothing", 0, False, "archived"),
    ("Applied", "applied", 1, False, "applied"),
    ("OA Received", "oa-received", 2, False, "interview"),
    ("Interview Scheduled", "interview-scheduled", 3, False, "interview"),
    ("Positive Hear Back", "positive-hear-back", 4, False, "interview"),
    ("Ghosted", "ghosted", 5, True, "archived"),
    ("Rejection", "rejection", 6, True, "rejected"),
    ("Offer Received", "offer-received", 7, True, "offer"),
    ("Withdrawn", "withdrawn", 8, True, "withdrawn"),
)


def upgrade() -> None:
    statuses = sa.table(
        "application_statuses",
        sa.column("name", sa.String()),
        sa.column("slug", sa.String()),
        sa.column("sort_order", sa.Integer()),
        sa.column("is_terminal", sa.Boolean()),
        sa.column("standard_category", sa.String()),
        sa.column("user_id", sa.Integer()),
        sa.column("is_custom", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    bind = op.get_bind()
    for name, slug, sort_order, is_terminal, standard_category in DEFAULT_APPLICATION_STATUSES:
        exists = bind.scalar(
            sa.select(sa.literal(1))
            .select_from(statuses)
            .where(statuses.c.user_id.is_(None), sa.func.lower(statuses.c.slug) == slug)
            .limit(1)
        )
        if exists is not None:
            continue
        now = datetime.now(timezone.utc)
        bind.execute(
            statuses.insert().values(
                name=name,
                slug=slug,
                sort_order=sort_order,
                is_terminal=is_terminal,
                standard_category=standard_category,
                user_id=None,
                is_custom=False,
                created_at=now,
                updated_at=now,
            )
        )


def downgrade() -> None:
    # Reference rows may be linked to application history. Keep them during a
    # code rollback instead of risking destructive cascade or FK failures.
    pass
