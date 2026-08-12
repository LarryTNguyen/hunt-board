"""merge generalized discovery with the later ingestion migrations

Revision ID: 202608030015
Revises: 202607310014, 202608030014
Create Date: 2026-08-03
"""

from __future__ import annotations

from collections.abc import Sequence


revision = "202608030015"
down_revision: tuple[str, str] = ("202607310014", "202608030014")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Join the two Milestone 6 descendant branches without changing schema."""


def downgrade() -> None:
    """Split back to the two parent heads without changing schema."""
