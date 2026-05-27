"""Persistence for the cloud ingestion API (SQLite or PostgreSQL)."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from cloud.api.database import (
    DbConnection,
    DbRow,
    connect,
    default_sqlite_path,
    is_postgres,
)
from cloud.api.env_validation import is_production, should_auto_create_schema

DEV_API_KEY = "fl_dev_local"


def db_path():
    return default_sqlite_path()


def now_ms() -> int:
    return int(time.time() * 1000)


def init_db(conn: DbConnection) -> None:
    """Create schema in-process (development/test). Production uses Alembic."""
    if not should_auto_create_schema():
        return
    # BIGINT for *_ms columns — PostgreSQL INTEGER overflows on Unix epoch ms.
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            auth_provider TEXT,
            created_at_ms BIGINT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS api_keys (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id),
            key_value TEXT NOT NULL UNIQUE,
            label TEXT NOT NULL,
            created_at_ms BIGINT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id),
            name TEXT NOT NULL,
            created_at_ms BIGINT NOT NULL,
            UNIQUE (user_id, name)
        );

        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id),
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            tags_json TEXT NOT NULL DEFAULT '[]',
            latest_step INTEGER NOT NULL DEFAULT 0,
            latest_loss REAL,
            created_at_ms BIGINT NOT NULL,
            updated_at_ms BIGINT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS metrics (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(id),
            step INTEGER NOT NULL,
            metrics_json TEXT NOT NULL,
            timestamp_ms BIGINT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(id),
            event_type TEXT NOT NULL,
            level TEXT NOT NULL,
            message TEXT NOT NULL,
            timestamp_ms BIGINT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_runs_project ON runs(project_id);
        CREATE INDEX IF NOT EXISTS idx_metrics_run ON metrics(run_id, step);
        CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id, timestamp_ms);

        CREATE TABLE IF NOT EXISTS usage_counters (
            user_id TEXT PRIMARY KEY REFERENCES users(id),
            runs_created INTEGER NOT NULL DEFAULT 0,
            metric_points_ingested INTEGER NOT NULL DEFAULT 0,
            events_ingested INTEGER NOT NULL DEFAULT 0,
            checkpoints_created INTEGER NOT NULL DEFAULT 0,
            checkpoint_bytes_uploaded BIGINT NOT NULL DEFAULT 0,
            last_used_at_ms BIGINT
        );

        CREATE TABLE IF NOT EXISTS checkpoints (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(id),
            step INTEGER NOT NULL,
            size_bytes BIGINT NOT NULL,
            path TEXT NOT NULL,
            status TEXT NOT NULL,
            metadata_json TEXT,
            created_at_ms BIGINT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_checkpoints_run ON checkpoints(run_id, step);

        CREATE TABLE IF NOT EXISTS run_launch_configs (
            run_id TEXT PRIMARY KEY REFERENCES runs(id),
            launch_type TEXT NOT NULL,
            command_json TEXT,
            script_path TEXT,
            working_dir TEXT,
            environment_json TEXT,
            created_at_ms BIGINT NOT NULL,
            updated_at_ms BIGINT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS run_resume_launches (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(id),
            launch_type TEXT NOT NULL,
            pid INTEGER,
            slurm_job_id TEXT,
            command_json TEXT,
            launched_at_ms BIGINT NOT NULL,
            status TEXT NOT NULL,
            error_message TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_resume_launches_run
            ON run_resume_launches(run_id, launched_at_ms DESC);

        CREATE TABLE IF NOT EXISTS user_alert_settings (
            user_id TEXT PRIMARY KEY REFERENCES users(id),
            alert_email TEXT,
            discord_webhook_url TEXT,
            slack_webhook_url TEXT,
            updated_at_ms BIGINT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS background_tasks (
            id TEXT PRIMARY KEY,
            user_id TEXT REFERENCES users(id),
            task_type TEXT NOT NULL,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            result_json TEXT,
            error_message TEXT,
            created_at_ms BIGINT NOT NULL,
            updated_at_ms BIGINT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_background_tasks_status
            ON background_tasks(status, created_at_ms DESC);

        CREATE TABLE IF NOT EXISTS alert_deliveries (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id),
            run_id TEXT,
            alert_type TEXT NOT NULL,
            channel TEXT NOT NULL,
            message TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at_ms BIGINT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_alert_deliveries_user
            ON alert_deliveries(user_id, created_at_ms DESC);

        CREATE TABLE IF NOT EXISTS user_oauth_accounts (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id),
            provider TEXT NOT NULL,
            provider_user_id TEXT NOT NULL,
            provider_email TEXT,
            linked_at_ms BIGINT NOT NULL,
            last_login_at_ms BIGINT NOT NULL,
            UNIQUE(provider, provider_user_id),
            UNIQUE(user_id, provider)
        );
        """
    )
    _migrate_schema(conn)
    _migrate_bigint_timestamps(conn)
    _merge_duplicate_emails(conn)
    conn.commit()
    seed_dev_user(conn)


def _migrate_schema(conn: DbConnection) -> None:
    if not conn.column_exists("runs", "latest_checkpoint_step"):
        conn.execute(
            "ALTER TABLE runs ADD COLUMN latest_checkpoint_step INTEGER NOT NULL DEFAULT 0"
        )
    if not conn.table_exists("run_launch_configs"):
        conn.executescript(
            """
            CREATE TABLE run_launch_configs (
                run_id TEXT PRIMARY KEY REFERENCES runs(id),
                launch_type TEXT NOT NULL,
                command_json TEXT,
                script_path TEXT,
                working_dir TEXT,
                environment_json TEXT,
                created_at_ms BIGINT NOT NULL,
                updated_at_ms BIGINT NOT NULL
            );
            """
        )
    if not conn.table_exists("run_resume_launches"):
        conn.executescript(
            """
            CREATE TABLE run_resume_launches (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES runs(id),
                launch_type TEXT NOT NULL,
                pid INTEGER,
                slurm_job_id TEXT,
                command_json TEXT,
                launched_at_ms BIGINT NOT NULL,
                status TEXT NOT NULL,
                error_message TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_resume_launches_run
                ON run_resume_launches(run_id, launched_at_ms DESC);
            """
        )
    if not conn.column_exists("users", "password_hash"):
        conn.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
    if not conn.column_exists("users", "auth_provider"):
        conn.execute("ALTER TABLE users ADD COLUMN auth_provider TEXT")
    if not conn.column_exists("api_keys", "last_used_at_ms"):
        conn.execute("ALTER TABLE api_keys ADD COLUMN last_used_at_ms BIGINT")
    if not conn.column_exists("checkpoints", "storage_backend"):
        conn.execute(
            "ALTER TABLE checkpoints ADD COLUMN storage_backend TEXT NOT NULL DEFAULT 'local'"
        )
    if not conn.column_exists("checkpoints", "storage_path"):
        conn.execute("ALTER TABLE checkpoints ADD COLUMN storage_path TEXT")
    if not conn.column_exists("checkpoints", "checksum_sha256"):
        conn.execute("ALTER TABLE checkpoints ADD COLUMN checksum_sha256 TEXT")
    if conn.column_exists("checkpoints", "storage_path"):
        conn.execute(
            """
            UPDATE checkpoints
            SET storage_path = path
            WHERE (storage_path IS NULL OR storage_path = '')
              AND path IS NOT NULL AND path != ''
            """
        )
        conn.execute(
            """
            UPDATE checkpoints
            SET storage_backend = 'local'
            WHERE storage_backend IS NULL OR storage_backend = ''
            """
        )


# (table, column) — epoch milliseconds exceed PostgreSQL INTEGER max.
_BIGINT_TIMESTAMP_COLUMNS: tuple[tuple[str, str], ...] = (
    ("users", "created_at_ms"),
    ("api_keys", "created_at_ms"),
    ("api_keys", "last_used_at_ms"),
    ("projects", "created_at_ms"),
    ("runs", "created_at_ms"),
    ("runs", "updated_at_ms"),
    ("metrics", "timestamp_ms"),
    ("events", "timestamp_ms"),
    ("usage_counters", "last_used_at_ms"),
    ("usage_counters", "checkpoint_bytes_uploaded"),
    ("checkpoints", "size_bytes"),
    ("checkpoints", "created_at_ms"),
    ("run_launch_configs", "created_at_ms"),
    ("run_launch_configs", "updated_at_ms"),
    ("run_resume_launches", "launched_at_ms"),
    ("user_alert_settings", "updated_at_ms"),
    ("background_tasks", "created_at_ms"),
    ("background_tasks", "updated_at_ms"),
    ("alert_deliveries", "created_at_ms"),
)


def _migrate_bigint_timestamps(conn: DbConnection) -> None:
    """Upgrade INTEGER timestamp/byte columns created before v19.0.1."""
    if not is_postgres():
        return
    for table, column in _BIGINT_TIMESTAMP_COLUMNS:
        if conn.column_exists(table, column):
            conn.execute(
                f"ALTER TABLE {table} ALTER COLUMN {column} TYPE BIGINT"
            )


def _merge_duplicate_emails(conn: DbConnection) -> None:
    """
    Legacy safeguard: if the users table was created without a UNIQUE(email)
    constraint in older local DBs, duplicates can exist. That breaks the model
    where sessions and API keys should reference the same user row.

    We merge duplicates by picking the earliest-created user as canonical and
    repointing foreign keys (api_keys, projects, usage_counters) to it.
    """
    duplicates = conn.execute(
        """
        SELECT email
        FROM users
        GROUP BY email
        HAVING COUNT(*) > 1
        """
    ).fetchall()
    for dup in duplicates:
        email = str(dup["email"])
        rows = conn.execute(
            """
            SELECT id, created_at_ms
            FROM users
            WHERE email = ?
            ORDER BY created_at_ms ASC
            """,
            (email,),
        ).fetchall()
        if len(rows) <= 1:
            continue
        canonical_id = str(rows[0]["id"])
        for row in rows[1:]:
            old_id = str(row["id"])
            # Repoint owned objects.
            conn.execute("UPDATE api_keys SET user_id = ? WHERE user_id = ?", (canonical_id, old_id))
            conn.execute("UPDATE projects SET user_id = ? WHERE user_id = ?", (canonical_id, old_id))
            conn.execute("UPDATE usage_counters SET user_id = ? WHERE user_id = ?", (canonical_id, old_id))
            conn.execute("DELETE FROM users WHERE id = ?", (old_id,))


def api_key_prefix(key_value: str) -> str:
    if len(key_value) <= 12:
        return key_value
    return f"{key_value[:12]}..."


def resolve_api_key(conn: DbConnection, api_key: str) -> DbRow | None:
    return conn.execute(
        """
        SELECT id, user_id, key_value, label, created_at_ms
        FROM api_keys
        WHERE key_value = ?
        """,
        (api_key,),
    ).fetchone()


def get_user_by_oauth(
    conn: DbConnection,
    provider: str,
    provider_user_id: str,
) -> DbRow | None:
    return conn.execute(
        """
        SELECT u.id, u.email, u.password_hash, u.auth_provider, u.created_at_ms
        FROM user_oauth_accounts oa
        JOIN users u ON u.id = oa.user_id
        WHERE oa.provider = ? AND oa.provider_user_id = ?
        """,
        (provider, provider_user_id),
    ).fetchone()


def upsert_oauth_account(
    conn: DbConnection,
    user_id: str,
    provider: str,
    provider_user_id: str,
    provider_email: str | None,
) -> None:
    now = now_ms()
    row = conn.execute(
        """
        SELECT id FROM user_oauth_accounts
        WHERE provider = ? AND provider_user_id = ?
        """,
        (provider, provider_user_id),
    ).fetchone()
    if row is None:
        conn.execute(
            """
            INSERT INTO user_oauth_accounts (
                id, user_id, provider, provider_user_id, provider_email, linked_at_ms, last_login_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                user_id,
                provider,
                provider_user_id,
                provider_email,
                now,
                now,
            ),
        )
        return
    conn.execute(
        """
        UPDATE user_oauth_accounts
        SET user_id = ?, provider_email = ?, last_login_at_ms = ?
        WHERE provider = ? AND provider_user_id = ?
        """,
        (user_id, provider_email, now, provider, provider_user_id),
    )


def list_oauth_accounts(conn: DbConnection, user_id: str) -> list[DbRow]:
    return conn.execute(
        """
        SELECT provider, provider_email, linked_at_ms, last_login_at_ms
        FROM user_oauth_accounts
        WHERE user_id = ?
        ORDER BY linked_at_ms ASC
        """,
        (user_id,),
    ).fetchall()


def get_user(conn: DbConnection, user_id: str) -> DbRow | None:
    return conn.execute(
        "SELECT id, email, password_hash, created_at_ms FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()


def seed_dev_user(conn: DbConnection) -> None:
    if is_production():
        return
    row = conn.execute(
        "SELECT id FROM api_keys WHERE key_value = ?",
        (DEV_API_KEY,),
    ).fetchone()
    if row is not None:
        return

    user_id = str(uuid.uuid4())
    created = now_ms()
    conn.execute(
        "INSERT INTO users (id, email, created_at_ms) VALUES (?, ?, ?)",
        (user_id, "dev@faultline.local", created),
    )
    conn.execute(
        """
        INSERT INTO api_keys (id, user_id, key_value, label, created_at_ms)
        VALUES (?, ?, ?, ?, ?)
        """,
        (str(uuid.uuid4()), user_id, DEV_API_KEY, "local-dev", created),
    )
    conn.commit()


def resolve_user_id(conn: DbConnection, api_key: str) -> str | None:
    row = resolve_api_key(conn, api_key)
    if row is None:
        return None
    return str(row["user_id"])


def touch_api_key_last_used(conn: DbConnection, api_key_id: str) -> None:
    conn.execute(
        "UPDATE api_keys SET last_used_at_ms = ? WHERE id = ?",
        (now_ms(), api_key_id),
    )


def list_api_keys(conn: DbConnection, user_id: str) -> list[DbRow]:
    return conn.execute(
        """
        SELECT id, key_value, label, created_at_ms, last_used_at_ms
        FROM api_keys
        WHERE user_id = ?
        ORDER BY created_at_ms DESC
        """,
        (user_id,),
    ).fetchall()


def row_to_api_key_list_item(row: DbRow) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "prefix": api_key_prefix(str(row["key_value"])),
        "label": str(row["label"]),
        "created_at_ms": int(row["created_at_ms"]),
        "last_used_at_ms": row["last_used_at_ms"],
    }


def get_or_create_project(conn: DbConnection, user_id: str, name: str) -> str:
    row = conn.execute(
        "SELECT id FROM projects WHERE user_id = ? AND name = ?",
        (user_id, name),
    ).fetchone()
    if row is not None:
        return str(row["id"])

    project_id = str(uuid.uuid4())
    created = now_ms()
    conn.execute(
        "INSERT INTO projects (id, user_id, name, created_at_ms) VALUES (?, ?, ?, ?)",
        (project_id, user_id, name, created),
    )
    conn.commit()
    return project_id


def row_to_run(row: DbRow, project_name: str) -> dict[str, Any]:
    tags = json.loads(row["tags_json"] or "[]")
    keys = row.keys()
    latest_checkpoint_step = (
        int(row["latest_checkpoint_step"])
        if "latest_checkpoint_step" in keys
        else 0
    )
    return {
        "run_id": row["id"],
        "project_name": project_name,
        "run_name": row["name"],
        "status": row["status"],
        "tags": tags,
        "latest_step": row["latest_step"],
        "latest_loss": row["latest_loss"],
        "latest_checkpoint_step": latest_checkpoint_step,
        "created_at_ms": row["created_at_ms"],
        "updated_at_ms": row["updated_at_ms"],
    }


def row_to_checkpoint(row: DbRow) -> dict[str, Any]:
    keys = row.keys()
    storage_path = (
        str(row["storage_path"])
        if "storage_path" in keys and row["storage_path"]
        else str(row["path"])
    )
    result: dict[str, Any] = {
        "checkpoint_id": row["id"],
        "run_id": row["run_id"],
        "step": int(row["step"]),
        "size_bytes": int(row["size_bytes"]),
        "status": row["status"],
        "metadata_json": row["metadata_json"],
        "created_at_ms": int(row["created_at_ms"]),
        "storage_backend": (
            str(row["storage_backend"]) if "storage_backend" in keys else "local"
        ),
        "storage_path": storage_path,
    }
    if "checksum_sha256" in keys and row["checksum_sha256"]:
        result["checksum_sha256"] = str(row["checksum_sha256"])
    return result
