"""Health and readiness probes for deployment."""

from __future__ import annotations

import os
from typing import Any

from cloud.api.database import connect, database_url, is_postgres
from cloud.api.storage import get_checkpoint_storage, storage_backend_name
from cloud.api.worker import worker_status


def app_version() -> str:
    return os.environ.get("FAULTLINE_CLOUD_VERSION", "24.0")


def database_kind() -> str:
    return "postgresql" if is_postgres() else "sqlite"


def check_database() -> tuple[str, str | None]:
    try:
        conn = connect()
        conn.execute("SELECT 1")
        conn.close()
        return "ok", None
    except Exception as error:  # noqa: BLE001
        return "error", str(error)


def check_checkpoints_storage() -> tuple[str, str | None]:
    try:
        return get_checkpoint_storage().health_probe()
    except Exception as error:  # noqa: BLE001
        return "error", str(error)


def check_worker() -> tuple[str, str | None]:
    status = worker_status()
    if status.get("healthy") and status.get("running"):
        return "ok", None
    if status.get("running"):
        return "ok", status.get("last_error")
    return "error", status.get("last_error") or "worker not running"


def infrastructure_payload() -> dict[str, Any]:
    db_status, db_error = check_database()
    ckpt_status, ckpt_error = check_checkpoints_storage()
    worker_ok, worker_error = check_worker()
    return {
        "version": app_version(),
        "database": {
            "kind": database_kind(),
            "url_redacted": _redact_database_url(database_url()),
            "status": db_status,
            "error": db_error,
        },
        "object_storage": {
            "backend": storage_backend_name(),
            "status": ckpt_status,
            "error": ckpt_error,
        },
        "background_worker": {
            "status": worker_ok,
            "error": worker_error,
            **worker_status(),
        },
    }


def _redact_database_url(url: str) -> str:
    if "@" in url and "://" in url:
        prefix, rest = url.split("://", 1)
        if "@" in rest:
            creds, host = rest.rsplit("@", 1)
            return f"{prefix}://***@{host}"
    return url


def health_payload() -> dict[str, Any]:
    db_status, db_error = check_database()
    ckpt_status, ckpt_error = check_checkpoints_storage()
    worker_ok, worker_error = check_worker()
    overall = "ok" if db_status == "ok" and ckpt_status == "ok" else "degraded"
    return {
        "status": overall,
        "service": "faultline-cloud-api",
        "version": app_version(),
        "database": db_status,
        "database_kind": database_kind(),
        "checkpoints_storage": ckpt_status,
        "storage_backend": storage_backend_name(),
        "background_worker": worker_ok,
        "database_error": db_error,
        "checkpoints_error": ckpt_error,
        "worker_error": worker_error,
    }


def ready_payload() -> dict[str, Any]:
    db_status, db_error = check_database()
    ready = db_status == "ok"
    return {
        "ready": ready,
        "status": "ok" if ready else "not_ready",
        "service": "faultline-cloud-api",
        "version": app_version(),
        "database": db_status,
        "database_error": db_error,
    }
