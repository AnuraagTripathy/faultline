"""Production startup validation and environment helpers."""

from __future__ import annotations

import os


def faultline_env() -> str:
    return os.environ.get("FAULTLINE_ENV", "development").strip().lower()


def is_production() -> bool:
    return faultline_env() == "production"


def should_auto_create_schema() -> bool:
    """Auto-create tables via init_db — development/test only."""
    raw = os.environ.get("FAULTLINE_DB_AUTO_CREATE", "").strip().lower()
    if raw in ("0", "false", "no"):
        return False
    if raw in ("1", "true", "yes"):
        return True
    return not is_production()


def validate_startup_config() -> None:
    """Fail fast when production is misconfigured."""
    if not is_production():
        return

    db_url = os.environ.get("FAULTLINE_DATABASE_URL", "").strip()
    if not db_url:
        raise RuntimeError(
            "FAULTLINE_DATABASE_URL must be set in production (managed PostgreSQL)"
        )
    if not db_url.startswith("postgresql"):
        raise RuntimeError(
            "FAULTLINE_DATABASE_URL must be a PostgreSQL URL in production"
        )

    jwt = os.environ.get("FAULTLINE_JWT_SECRET", "").strip()
    if len(jwt) < 32:
        raise RuntimeError(
            "FAULTLINE_JWT_SECRET must be set to at least 32 characters in production"
        )

    if os.environ.get("FAULTLINE_SEED_DEMO", "").strip().lower() in ("1", "true", "yes"):
        raise RuntimeError("FAULTLINE_SEED_DEMO must not be enabled in production")

    secure = os.environ.get("FAULTLINE_COOKIE_SECURE", "").strip().lower()
    if secure not in ("1", "true", "yes"):
        raise RuntimeError("FAULTLINE_COOKIE_SECURE must be true in production")
