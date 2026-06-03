"""Run Alembic migrations programmatically.

Used at app startup (when a database URL is configured) and by tests, so the
schema is always built through migrations rather than ``create_all``.
"""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def run_migrations(url: str, revision: str = "head") -> None:
    """Upgrade the database at ``url`` to ``revision`` (default: latest)."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, revision)
