"""Seed realistic demo runs for local Docker and onboarding (v21.0)."""

from __future__ import annotations

import json
import os
import pickle
import uuid
from typing import Any

from cloud.api.checkpoints import get_checkpoint_storage
from cloud.api.db import (
    DEV_API_KEY,
    connect,
    get_or_create_project,
    now_ms,
    resolve_user_id,
)
from cloud.api.run_events import log_run_event
from cloud.api.usage import increment_usage
from cloud.api.user_accounts import create_user_with_password, get_user_by_email, normalize_email

DEMO_EMAIL = "demo@faultline.local"
DEMO_PASSWORD = "faultlinedemo"
DEMO_PROJECT = "faultline-demo"
DEMO_MARKER = "integration:demo-seed-v21"


def _user_id_for_key(conn: Any, api_key: str) -> str | None:
    return resolve_user_id(conn, api_key)


def _ensure_demo_user(conn: Any) -> str:
    row = get_user_by_email(conn, DEMO_EMAIL)
    if row is not None:
        return str(row["id"])
    try:
        created = create_user_with_password(conn, DEMO_EMAIL, DEMO_PASSWORD)
        return str(created["id"])
    except ValueError:
        row = get_user_by_email(conn, DEMO_EMAIL)
        if row is None:
            raise
        return str(row["id"])


def _has_demo_runs(conn: Any, user_id: str) -> bool:
    row = conn.execute(
        """
        SELECT r.id FROM runs r
        JOIN projects p ON p.id = r.project_id
        WHERE p.user_id = ? AND p.name = ? AND r.tags_json LIKE ?
        LIMIT 1
        """,
        (user_id, DEMO_PROJECT, f"%{DEMO_MARKER}%"),
    ).fetchone()
    return row is not None


def _insert_metrics(
    conn: Any,
    *,
    user_id: str,
    run_id: str,
    steps: range,
    loss_fn: Any,
) -> None:
    for step in steps:
        ts = now_ms()
        metrics = {"loss": float(loss_fn(step)), "progress_pct": min(100.0, step / 5.0)}
        conn.execute(
            """
            INSERT INTO metrics (id, run_id, step, metrics_json, timestamp_ms)
            VALUES (?, ?, ?, ?, ?)
            """,
            (str(uuid.uuid4()), run_id, step, json.dumps(metrics), ts),
        )
        conn.execute(
            """
            UPDATE runs
            SET latest_step = ?, latest_loss = ?, updated_at_ms = ?
            WHERE id = ?
            """,
            (step, metrics["loss"], ts, run_id),
        )
    increment_usage(conn, user_id, metric_points_ingested=len(list(steps)))


def _insert_checkpoint(
    conn: Any,
    *,
    user_id: str,
    run_id: str,
    step: int,
) -> None:
    from cloud.api.checkpoints import checkpoint_filename_for_step
    from cloud.api.storage import LocalCloudCheckpointStorage

    storage = get_checkpoint_storage()
    payload = pickle.dumps({"step": step, "demo": True, "weights": [0.1, 0.2, 0.3]})
    checkpoint_id = str(uuid.uuid4())
    filename = checkpoint_filename_for_step(step)
    stored = storage.save_checkpoint(
        user_id,
        run_id,
        checkpoint_id,
        filename,
        payload,
    )
    created = now_ms()
    if isinstance(storage, LocalCloudCheckpointStorage):
        legacy_path = str(storage.root / stored.storage_path)
    else:
        legacy_path = stored.storage_path
    conn.execute(
        """
        INSERT INTO checkpoints (
            id, run_id, step, size_bytes, path, status,
            metadata_json, created_at_ms,
            storage_backend, storage_path, checksum_sha256
        ) VALUES (?, ?, ?, ?, ?, 'committed', ?, ?, ?, ?, ?)
        """,
        (
            checkpoint_id,
            run_id,
            step,
            stored.size_bytes,
            legacy_path,
            json.dumps({"demo": True, "step": step}),
            created,
            stored.storage_backend,
            stored.storage_path,
            stored.checksum_sha256,
        ),
    )
    conn.execute(
        """
        UPDATE runs SET latest_checkpoint_step = ?, updated_at_ms = ? WHERE id = ?
        """,
        (step, created, run_id),
    )
    increment_usage(
        conn,
        user_id,
        checkpoints_created=1,
        checkpoint_bytes_uploaded=len(payload),
    )


def _create_run(
    conn: Any,
    *,
    user_id: str,
    project_id: str,
    name: str,
    status: str,
    tags: list[str],
    latest_step: int = 0,
    latest_loss: float | None = None,
    latest_checkpoint_step: int = 0,
) -> str:
    run_id = str(uuid.uuid4())
    created = now_ms()
    merged_tags = tags + [DEMO_MARKER]
    conn.execute(
        """
        INSERT INTO runs (
            id, project_id, name, status, tags_json,
            latest_step, latest_loss, latest_checkpoint_step,
            created_at_ms, updated_at_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            project_id,
            name,
            status,
            json.dumps(merged_tags),
            latest_step,
            latest_loss,
            latest_checkpoint_step,
            created,
            created,
        ),
    )
    increment_usage(conn, user_id, runs_created=1)
    return run_id


def seed_demo_data(conn: Any | None = None) -> dict[str, Any]:
    """Idempotent demo dataset for Docker / first launch."""
    own = conn is None
    if own:
        conn = connect()
    try:
        demo_user_id = _ensure_demo_user(conn)
        dev_user_id = _user_id_for_key(conn, DEV_API_KEY)
        user_ids = [demo_user_id]
        if dev_user_id and dev_user_id not in user_ids:
            user_ids.append(dev_user_id)

        created_runs: list[str] = []
        for user_id in user_ids:
            if _has_demo_runs(conn, user_id):
                continue
            project_id = get_or_create_project(conn, user_id, DEMO_PROJECT)

            # 1) Running job
            running_id = _create_run(
                conn,
                user_id=user_id,
                project_id=project_id,
                name="resnet-finetune-live",
                status="running",
                tags=["integration:pytorch", "quickstart"],
            )
            _insert_metrics(
                conn,
                user_id=user_id,
                run_id=running_id,
                steps=range(0, 181, 4),
                loss_fn=lambda s: 2.0 * (0.98**s),
            )
            _insert_checkpoint(conn, user_id=user_id, run_id=running_id, step=160)
            created_runs.append(running_id)

            # 2) Failed recoverable (Slurm)
            failed_id = _create_run(
                conn,
                user_id=user_id,
                project_id=project_id,
                name="slurm-protein-exp7",
                status="running",
                tags=["integration:lightning", "hpc"],
            )
            _insert_metrics(
                conn,
                user_id=user_id,
                run_id=failed_id,
                steps=range(0, 401, 5),
                loss_fn=lambda s: 1.5 / (1.0 + s * 0.01),
            )
            for cp_step in (100, 200, 300, 400):
                _insert_checkpoint(conn, user_id=user_id, run_id=failed_id, step=cp_step)
            log_run_event(
                conn,
                failed_id,
                user_id,
                event_type="faultline.run.failed",
                level="error",
                message="simulated node eviction (demo)",
            )
            created_runs.append(failed_id)

            # 3) Completed HuggingFace-style
            done_id = _create_run(
                conn,
                user_id=user_id,
                project_id=project_id,
                name="llama-alpaca-finetune",
                status="running",
                tags=["integration:huggingface"],
            )
            _insert_metrics(
                conn,
                user_id=user_id,
                run_id=done_id,
                steps=range(0, 501, 10),
                loss_fn=lambda s: 0.8 * (0.995**s),
            )
            _insert_checkpoint(conn, user_id=user_id, run_id=done_id, step=500)
            log_run_event(
                conn,
                done_id,
                user_id,
                event_type="faultline.run.completed",
                level="info",
                message="training completed (demo)",
            )
            created_runs.append(done_id)

        conn.commit()
        return {
            "seeded": bool(created_runs),
            "run_ids": created_runs,
            "demo_email": DEMO_EMAIL,
            "demo_password": DEMO_PASSWORD,
            "api_key": DEV_API_KEY,
        }
    finally:
        if own:
            conn.close()


def should_seed_demo() -> bool:
    return os.environ.get("FAULTLINE_SEED_DEMO", "").lower() in ("1", "true", "yes")
