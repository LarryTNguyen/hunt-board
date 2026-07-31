from __future__ import annotations

"""Removed Milestone 1 compatibility module.

Route code must use ``require_user``/``require_admin`` from
``hunt_board.auth.dependencies``. Offline tests may explicitly override those
dependencies with ``hunt_board.auth.testing.get_test_user``.
"""
