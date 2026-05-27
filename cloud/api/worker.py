"""Lightweight in-process background task worker (v19.0)."""

from __future__ import annotations

import json
import queue
import threading
import uuid
from typing import Any, Callable

from cloud.api.alerts import evaluate_user_alerts, send_run_alert
from cloud.api.database import DbConnection, connect
from cloud.api.db import now_ms
from cloud.api.recovery import check_checkpoint_health, compute_recovery_summary
from cloud.api.resume_launcher import execute_resume
from cloud.api.storage import checkpoint_storage_path, get_checkpoint_storage

TASK_VERIFY_CHECKPOINT = "verify_checkpoint"
TASK_EVALUATE_ALERTS = "evaluate_alerts"
TASK_RESUME_RUN = "resume_run"

_task_queue: queue.Queue[str] = queue.Queue()
_worker_thread: threading.Thread | None = None
_worker_lock = threading.Lock()
_worker_healthy = False
_worker_last_error: str | None = None


def worker_status() -> dict[str, Any]:
    with _worker_lock:
        return {
            "healthy": _worker_healthy,
            "running": _worker_thread is not None and _worker_thread.is_alive(),
            "last_error": _worker_last_error,
            "queue_size": _task_queue.qsize(),
        }


def start_worker() -> None:
    global _worker_thread, _worker_healthy
    with _worker_lock:
        if _worker_thread is not None and _worker_thread.is_alive():
            return
        _worker_healthy = True
        _worker_thread = threading.Thread(
            target=_worker_loop,
            name="faultline-worker",
            daemon=True,
        )
        _worker_thread.start()


def enqueue_task(
    task_type: str,
    payload: dict[str, Any],
    *,
    user_id: str | None = None,
) -> str:
    """Persist task and queue for background execution."""
    task_id = str(uuid.uuid4())
    created = now_ms()
    conn = connect()
    try:
        conn.execute(
            """
            INSERT INTO background_tasks (
                id, user_id, task_type, status, payload_json,
                result_json, error_message, created_at_ms, updated_at_ms
            ) VALUES (?, ?, ?, 'queued', ?, NULL, NULL, ?, ?)
            """,
            (
                task_id,
                user_id,
                task_type,
                json.dumps(payload),
                created,
                created,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    _task_queue.put(task_id)
    return task_id


def list_tasks(
    conn: DbConnection,
    user_id: str,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, user_id, task_type, status, payload_json, result_json,
               error_message, created_at_ms, updated_at_ms
        FROM background_tasks
        WHERE user_id = ? OR user_id IS NULL
        ORDER BY created_at_ms DESC
        LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        result.append(
            {
                "task_id": str(row["id"]),
                "user_id": row["user_id"],
                "task_type": str(row["task_type"]),
                "status": str(row["status"]),
                "payload": json.loads(row["payload_json"] or "{}"),
                "result": json.loads(row["result_json"]) if row["result_json"] else None,
                "error_message": row["error_message"],
                "created_at_ms": int(row["created_at_ms"]),
                "updated_at_ms": int(row["updated_at_ms"]),
            }
        )
    return result


def _update_task(
    conn: DbConnection,
    task_id: str,
    *,
    status: str,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE background_tasks
        SET status = ?, result_json = ?, error_message = ?, updated_at_ms = ?
        WHERE id = ?
        """,
        (
            status,
            json.dumps(result) if result else None,
            error,
            now_ms(),
            task_id,
        ),
    )
    conn.commit()


def _worker_loop() -> None:
    global _worker_healthy, _worker_last_error
    while True:
        task_id = _task_queue.get()
        conn = connect()
        try:
            row = conn.execute(
                "SELECT * FROM background_tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
            if row is None:
                continue
            _update_task(conn, task_id, status="running")
            payload = json.loads(row["payload_json"] or "{}")
            user_id = str(row["user_id"]) if row["user_id"] else None
            task_type = str(row["task_type"])

            handler = _TASK_HANDLERS.get(task_type)
            if handler is None:
                _update_task(
                    conn,
                    task_id,
                    status="failed",
                    error=f"unknown task type: {task_type}",
                )
                continue

            result = handler(conn, payload, user_id=user_id)
            _update_task(conn, task_id, status="completed", result=result)
            with _worker_lock:
                _worker_last_error = None
        except Exception as error:  # noqa: BLE001
            with _worker_lock:
                _worker_last_error = str(error)
            try:
                _update_task(conn, task_id, status="failed", error=str(error))
            except Exception:
                pass
        finally:
            conn.close()
            _task_queue.task_done()


def _handle_verify_checkpoint(
    conn: DbConnection,
    payload: dict[str, Any],
    *,
    user_id: str | None,
) -> dict[str, Any]:
    del user_id
    checkpoint_id = str(payload["checkpoint_id"])
    row = conn.execute(
        "SELECT * FROM checkpoints WHERE id = ?",
        (checkpoint_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown checkpoint: {checkpoint_id}")

    storage = get_checkpoint_storage()
    path = checkpoint_storage_path(row)
    health = "unknown"
    if path:
        health = check_checkpoint_health(
            storage,
            path,
            int(row["size_bytes"]),
        )
    return {
        "checkpoint_id": checkpoint_id,
        "health": health,
        "storage_backend": str(
            row["storage_backend"] if "storage_backend" in row.keys() else "local"
        ),
    }


def _handle_evaluate_alerts(
    conn: DbConnection,
    payload: dict[str, Any],
    *,
    user_id: str | None,
) -> dict[str, Any]:
    del payload
    if not user_id:
        raise ValueError("evaluate_alerts requires user_id")
    sent = evaluate_user_alerts(conn, user_id)
    return {"alerts_sent": len(sent), "details": sent}


def _handle_resume_run(
    conn: DbConnection,
    payload: dict[str, Any],
    *,
    user_id: str | None,
) -> dict[str, Any]:
    from cloud.api.run_events import log_run_event

    run_id = str(payload["run_id"])
    row = conn.execute(
        """
        SELECT r.*, p.name AS project_name, p.user_id AS owner_id
        FROM runs r
        JOIN projects p ON p.id = r.project_id
        WHERE r.id = ?
        """,
        (run_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown run: {run_id}")
    owner = str(row["owner_id"])
    if user_id and owner != user_id:
        raise ValueError("run not owned by user")

    try:
        result = execute_resume(
            conn,
            row,
            project_name=str(row["project_name"]),
            user_id=owner,
            log_event_fn=log_run_event,
        )
    except Exception as error:
        send_run_alert(
            conn,
            user_id=owner,
            run_row=row,
            alert_type="resume_failure",
            status_label="resume failed",
        )
        raise

    return result


_TASK_HANDLERS: dict[str, Callable[..., dict[str, Any]]] = {
    TASK_VERIFY_CHECKPOINT: _handle_verify_checkpoint,
    TASK_EVALUATE_ALERTS: _handle_evaluate_alerts,
    TASK_RESUME_RUN: _handle_resume_run,
}
