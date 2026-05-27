"""Per-user usage counters for the cloud API."""

from __future__ import annotations

from cloud.api.database import DbConnection, is_postgres
from cloud.api.db import now_ms

USAGE_FIELDS = (
    "runs_created",
    "metric_points_ingested",
    "events_ingested",
    "checkpoints_created",
    "checkpoint_bytes_uploaded",
)


def ensure_usage_row(conn: DbConnection, user_id: str) -> None:
    if is_postgres():
        conn.execute(
            """
            INSERT INTO usage_counters (user_id)
            VALUES (?)
            ON CONFLICT (user_id) DO NOTHING
            """,
            (user_id,),
        )
    else:
        conn.execute(
            "INSERT OR IGNORE INTO usage_counters (user_id) VALUES (?)",
            (user_id,),
        )


def touch_last_used(conn: DbConnection, user_id: str) -> None:
    ensure_usage_row(conn, user_id)
    conn.execute(
        "UPDATE usage_counters SET last_used_at_ms = ? WHERE user_id = ?",
        (now_ms(), user_id),
    )


def increment_usage(
    conn: DbConnection,
    user_id: str,
    *,
    runs_created: int = 0,
    metric_points_ingested: int = 0,
    events_ingested: int = 0,
    checkpoints_created: int = 0,
    checkpoint_bytes_uploaded: int = 0,
) -> None:
    ensure_usage_row(conn, user_id)
    touch_last_used(conn, user_id)
    conn.execute(
        """
        UPDATE usage_counters
        SET runs_created = runs_created + ?,
            metric_points_ingested = metric_points_ingested + ?,
            events_ingested = events_ingested + ?,
            checkpoints_created = checkpoints_created + ?,
            checkpoint_bytes_uploaded = checkpoint_bytes_uploaded + ?
        WHERE user_id = ?
        """,
        (
            runs_created,
            metric_points_ingested,
            events_ingested,
            checkpoints_created,
            checkpoint_bytes_uploaded,
            user_id,
        ),
    )


def get_usage(conn: DbConnection, user_id: str) -> dict[str, int | None]:
    ensure_usage_row(conn, user_id)
    row = conn.execute(
        "SELECT * FROM usage_counters WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    assert row is not None
    return {
        "runs_created": int(row["runs_created"]),
        "metric_points_ingested": int(row["metric_points_ingested"]),
        "events_ingested": int(row["events_ingested"]),
        "checkpoints_created": int(row["checkpoints_created"]),
        "checkpoint_bytes_uploaded": int(row["checkpoint_bytes_uploaded"]),
        "last_used_at_ms": row["last_used_at_ms"],
    }
