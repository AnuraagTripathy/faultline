"""Alembic migration runner for production deploys."""

from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from cloud.api.database import database_url, get_engine, reset_engine
from cloud.api.env_validation import is_production

logger = logging.getLogger("faultline.migrations")

_ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


def _alembic_config() -> Config:
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("script_location", str(_ALEMBIC_INI.parent / "alembic"))
    return cfg


def database_revision() -> str | None:
    """Revision stored in the database, or None if alembic_version is missing/empty."""
    reset_engine()
    engine = get_engine()
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        return context.get_current_revision()


def head_revision() -> str | None:
    script = ScriptDirectory.from_config(_alembic_config())
    heads = script.get_heads()
    if not heads:
        return None
    if len(heads) > 1:
        raise RuntimeError(f"multiple Alembic heads not supported: {heads}")
    return heads[0]


def run_pending_migrations() -> str:
    """
    Apply all pending migrations (alembic upgrade head).
    Returns the revision after upgrade. Raises if still behind head.
    """
    if is_production() and not database_url().strip():
        raise RuntimeError("FAULTLINE_DATABASE_URL is required in production")

    reset_engine()
    cfg = _alembic_config()
    before = database_revision()
    head = head_revision()
    logger.info(
        "running Alembic migrations (db=%s, current=%s, head=%s)",
        _safe_db_label(),
        before or "none",
        head,
    )
    command.upgrade(cfg, "head")
    reset_engine()
    after = database_revision()
    if head and after != head:
        raise RuntimeError(
            f"database migration incomplete: at {after!r}, expected head {head!r}"
        )
    logger.info("database at revision %s", after or head)
    return after or head or ""


def verify_migrations_at_head() -> None:
    """Fail fast if the database is not at the latest Alembic revision."""
    head = head_revision()
    current = database_revision()
    if head is None:
        return
    if current != head:
        raise RuntimeError(
            f"database schema out of date (revision {current!r}, head {head!r}); "
            "run: alembic -c cloud/alembic.ini upgrade head"
        )


def _safe_db_label() -> str:
    url = database_url()
    if url.startswith("sqlite"):
        return "sqlite"
    if "@" in url:
        return url.split("@", 1)[-1].split("?")[0]
    return "database"
