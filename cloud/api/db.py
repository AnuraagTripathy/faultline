"""SQLite persistence for the cloud ingestion API."""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "faultline.db"
DEV_API_KEY = "fl_dev_local"


def db_path() -> Path:
    raw = os.environ.get("FAULTLINE_CLOUD_DB")
    if raw:
        return Path(raw)
    return DEFAULT_DB_PATH


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def now_ms() -> int:
    return int(time.time() * 1000)


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            created_at_ms INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS api_keys (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id),
            key_value TEXT NOT NULL UNIQUE,
            label TEXT NOT NULL,
            created_at_ms INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id),
            name TEXT NOT NULL,
            created_at_ms INTEGER NOT NULL,
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
            created_at_ms INTEGER NOT NULL,
            updated_at_ms INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS metrics (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(id),
            step INTEGER NOT NULL,
            metrics_json TEXT NOT NULL,
            timestamp_ms INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(id),
            event_type TEXT NOT NULL,
            level TEXT NOT NULL,
            message TEXT NOT NULL,
            timestamp_ms INTEGER NOT NULL
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
            checkpoint_bytes_uploaded INTEGER NOT NULL DEFAULT 0,
            last_used_at_ms INTEGER
        );

        CREATE TABLE IF NOT EXISTS checkpoints (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(id),
            step INTEGER NOT NULL,
            size_bytes INTEGER NOT NULL,
            path TEXT NOT NULL,
            status TEXT NOT NULL,
            metadata_json TEXT,
            created_at_ms INTEGER NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_checkpoints_run ON checkpoints(run_id, step);
        """
    )
    _migrate_schema(conn)
    conn.commit()
    seed_dev_user(conn)


def _migrate_schema(conn: sqlite3.Connection) -> None:
    run_cols = {row[1] for row in conn.execute("PRAGMA table_info(runs)")}
    if "latest_checkpoint_step" not in run_cols:
        conn.execute(
            "ALTER TABLE runs ADD COLUMN latest_checkpoint_step INTEGER NOT NULL DEFAULT 0"
        )


def api_key_prefix(key_value: str) -> str:
    if len(key_value) <= 12:
        return key_value
    return f"{key_value[:12]}..."


def resolve_api_key(conn: sqlite3.Connection, api_key: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT id, user_id, key_value, label, created_at_ms
        FROM api_keys
        WHERE key_value = ?
        """,
        (api_key,),
    ).fetchone()


def get_user(conn: sqlite3.Connection, user_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, email, created_at_ms FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()


def seed_dev_user(conn: sqlite3.Connection) -> None:
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


def resolve_user_id(conn: sqlite3.Connection, api_key: str) -> str | None:
    row = resolve_api_key(conn, api_key)
    if row is None:
        return None
    return str(row["user_id"])


def get_or_create_project(conn: sqlite3.Connection, user_id: str, name: str) -> str:
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


def row_to_run(row: sqlite3.Row, project_name: str) -> dict[str, Any]:
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


def row_to_checkpoint(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "checkpoint_id": row["id"],
        "run_id": row["run_id"],
        "step": int(row["step"]),
        "size_bytes": int(row["size_bytes"]),
        "status": row["status"],
        "metadata_json": row["metadata_json"],
        "created_at_ms": int(row["created_at_ms"]),
    }
