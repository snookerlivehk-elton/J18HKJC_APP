"""Regression: SQLAlchemy 2.1+ defaults postgresql:// to psycopg (v3).

APP-CORN / meeting_tick crashed with ModuleNotFoundError: No module named 'psycopg'
when requirements only listed psycopg2-binary.
"""
from __future__ import annotations

import importlib

from sqlalchemy.engine import make_url


def test_default_postgresql_driver_is_importable():
    url = make_url("postgresql://user:pass@localhost:5432/j18db")
    driver = url.get_driver_name()
    # 2.1+ → psycopg; older 2.0.x → psycopg2
    assert driver in {"psycopg", "psycopg2"}, driver
    mod = importlib.import_module(driver)
    assert mod is not None


def test_legacy_psycopg2_direct_import_still_available():
    # Crawlers / init_pg still call `import psycopg2` directly.
    import psycopg2  # noqa: F401
