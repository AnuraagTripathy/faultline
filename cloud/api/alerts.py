"""User alert settings and alert evaluation."""

from __future__ import annotations

import json
import uuid
from typing import Any

from cloud.api.alert_delivery import deliver_user_alert, format_alert_message
from cloud.api.database import DbConnection
from cloud.api.db import now_ms
from cloud.api.recovery import compute_recovery_summary


def get_alert_settings(conn: DbConnection, user_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT user_id, alert_email, discord_webhook_url, slack_webhook_url, updated_at_ms
        FROM user_alert_settings
        WHERE user_id = ?
        """,
        (user_id,),
    ).fetchone()
    if row is None:
        return {
            "user_id": user_id,
            "alert_email": None,
            "discord_webhook_url": None,
            "slack_webhook_url": None,
            "updated_at_ms": None,
        }
    return {
        "user_id": str(row["user_id"]),
        "alert_email": row["alert_email"],
        "discord_webhook_url": row["discord_webhook_url"],
        "slack_webhook_url": row["slack_webhook_url"],
        "updated_at_ms": int(row["updated_at_ms"]),
    }


def upsert_alert_settings(
    conn: DbConnection,
    user_id: str,
    *,
    alert_email: str | None = None,
    discord_webhook_url: str | None = None,
    slack_webhook_url: str | None = None,
) -> dict[str, Any]:
    updated = now_ms()
    existing = conn.execute(
        "SELECT user_id FROM user_alert_settings WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if existing is None:
        conn.execute(
            """
            INSERT INTO user_alert_settings (
                user_id, alert_email, discord_webhook_url, slack_webhook_url, updated_at_ms
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, alert_email, discord_webhook_url, slack_webhook_url, updated),
        )
    else:
        conn.execute(
            """
            UPDATE user_alert_settings
            SET alert_email = ?, discord_webhook_url = ?, slack_webhook_url = ?, updated_at_ms = ?
            WHERE user_id = ?
            """,
            (alert_email, discord_webhook_url, slack_webhook_url, updated, user_id),
        )
    conn.commit()
    return get_alert_settings(conn, user_id)


def _has_any_channel(settings: dict[str, Any]) -> bool:
    return bool(
        settings.get("alert_email")
        or settings.get("discord_webhook_url")
        or settings.get("slack_webhook_url")
    )


def record_delivery(
    conn: DbConnection,
    *,
    user_id: str,
    run_id: str | None,
    alert_type: str,
    channel: str,
    message: str,
    status: str,
) -> None:
    conn.execute(
        """
        INSERT INTO alert_deliveries (
            id, user_id, run_id, alert_type, channel, message, status, created_at_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            user_id,
            run_id,
            alert_type,
            channel,
            message[:4000],
            status,
            now_ms(),
        ),
    )


def send_run_alert(
    conn: DbConnection,
    *,
    user_id: str,
    run_row: Any,
    alert_type: str,
    status_label: str,
) -> list[tuple[str, str]]:
    settings = get_alert_settings(conn, user_id)
    if not _has_any_channel(settings):
        return []

    project_name = str(run_row["project_name"])
    run_name = str(run_row["name"])
    run_id = str(run_row["id"])
    keys = run_row.keys()
    ckpt_step = (
        int(run_row["latest_checkpoint_step"])
        if "latest_checkpoint_step" in keys and run_row["latest_checkpoint_step"]
        else 0
    )

    message = format_alert_message(
        alert_type=alert_type,
        run_name=run_name,
        project_name=project_name,
        status=status_label,
        latest_checkpoint_step=ckpt_step if ckpt_step else None,
    )
    subject = f"Faultline: {alert_type} — {run_name}"

    results = deliver_user_alert(settings, subject=subject, message=message)
    for channel, channel_status in results:
        record_delivery(
            conn,
            user_id=user_id,
            run_id=run_id,
            alert_type=alert_type,
            channel=channel,
            message=message,
            status=channel_status,
        )
    conn.commit()
    return results


def evaluate_user_alerts(conn: DbConnection, user_id: str) -> list[dict[str, Any]]:
    """Scan runs for alert-worthy conditions and deliver notifications."""
    settings = get_alert_settings(conn, user_id)
    if not _has_any_channel(settings):
        return []

    rows = conn.execute(
        """
        SELECT r.*, p.name AS project_name
        FROM runs r
        JOIN projects p ON p.id = r.project_id
        WHERE p.user_id = ?
        ORDER BY r.updated_at_ms DESC
        LIMIT 50
        """,
        (user_id,),
    ).fetchall()

    sent: list[dict[str, Any]] = []
    for row in rows:
        summary = compute_recovery_summary(
            conn, row, project_name=str(row["project_name"])
        )
        alert_type: str | None = None
        status_label = str(summary.get("display_status", row["status"]))

        if summary.get("checkpoint_health") == "missing_file":
            alert_type = "checkpoint_failure"
        elif summary.get("is_stale"):
            alert_type = "stale_run"
        elif summary.get("recovery_badge") == "recoverable":
            alert_type = "recovery_available"
        elif str(row["status"]) == "failed":
            alert_type = "run_failed"

        if alert_type is None:
            continue

        # Dedupe: skip if same alert sent in last hour
        recent = conn.execute(
            """
            SELECT 1 FROM alert_deliveries
            WHERE user_id = ? AND run_id = ? AND alert_type = ?
              AND created_at_ms > ?
            LIMIT 1
            """,
            (user_id, str(row["id"]), alert_type, now_ms() - 3_600_000),
        ).fetchone()
        if recent is not None:
            continue

        channels = send_run_alert(
            conn,
            user_id=user_id,
            run_row=row,
            alert_type=alert_type,
            status_label=status_label,
        )
        if channels:
            sent.append(
                {
                    "run_id": str(row["id"]),
                    "alert_type": alert_type,
                    "channels": channels,
                }
            )
    return sent
