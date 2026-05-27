"""Run lifecycle event logging."""

from __future__ import annotations

import uuid
from typing import Any

from cloud.api.database import DbConnection
from cloud.api.db import now_ms
from cloud.api.usage import increment_usage

RUN_STATUS_EVENTS = {
    "faultline.run.completed": "completed",
    "faultline.run.failed": "failed",
    "faultline.run.stopped": "stopped",
}


def log_run_event(
    conn: DbConnection,
    run_id: str,
    user_id: str,
    event_type: str,
    level: str,
    message: str,
) -> None:
    timestamp = now_ms()
    conn.execute(
        """
        INSERT INTO events (id, run_id, event_type, level, message, timestamp_ms)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (str(uuid.uuid4()), run_id, event_type, level.lower(), message, timestamp),
    )
    new_status = RUN_STATUS_EVENTS.get(event_type)
    if new_status is not None:
        conn.execute(
            "UPDATE runs SET status = ?, updated_at_ms = ? WHERE id = ?",
            (new_status, timestamp, run_id),
        )
    elif event_type == "faultline.run.resume_started":
        conn.execute(
            "UPDATE runs SET status = 'running', updated_at_ms = ? WHERE id = ?",
            (timestamp, run_id),
        )
    else:
        conn.execute(
            "UPDATE runs SET updated_at_ms = ? WHERE id = ?",
            (timestamp, run_id),
        )
    increment_usage(conn, user_id, events_ingested=1)
    conn.commit()
