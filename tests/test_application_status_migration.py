from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa

from hunt_board.db.models import ApplicationStatus


def test_reference_status_migration_is_complete_and_idempotent(db_session, monkeypatch) -> None:
    migration_path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "202608140017_seed_application_status_reference_data.py"
    )
    spec = importlib.util.spec_from_file_location("application_status_reference_migration", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    connection = db_session.connection()
    monkeypatch.setattr(migration.op, "get_bind", lambda: connection)

    migration.upgrade()
    migration.upgrade()
    db_session.flush()

    rows = db_session.execute(
        sa.select(
            ApplicationStatus.slug,
            ApplicationStatus.standard_category,
            ApplicationStatus.is_terminal,
        )
        .where(ApplicationStatus.user_id.is_(None))
        .order_by(ApplicationStatus.sort_order)
    ).all()

    assert rows == [
        (slug, standard_category, is_terminal)
        for _, slug, _, is_terminal, standard_category in migration.DEFAULT_APPLICATION_STATUSES
    ]
