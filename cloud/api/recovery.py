"""Crash-to-resume recovery summary for cloud runs."""

from __future__ import annotations

from typing import Any, Literal

from cloud.api.db import now_ms, row_to_checkpoint
from cloud.api.launch_config import (
    get_latest_resume_launch,
    get_launch_config_row,
    row_to_launch_config,
)
from cloud.api.storage import (
    CloudCheckpointStorage,
    checkpoint_storage_path,
    get_checkpoint_storage,
)

STALE_RUN_THRESHOLD_MS = 60_000

CheckpointHealth = Literal["ok", "missing_file", "empty_file", "unknown"]
Recommendation = Literal["resume_from_checkpoint", "no_checkpoint", "run_completed"]
RestoreStatus = Literal["ready", "no_checkpoint", "unhealthy", "completed", "not_applicable"]
RecoveryBadge = Literal[
    "recoverable",
    "no_checkpoint",
    "completed",
    "checkpoint_missing",
    "stale",
    "resuming",
]


def check_checkpoint_health(
    storage: CloudCheckpointStorage,
    storage_path: str | None,
    size_bytes: int,
) -> CheckpointHealth:
    if not storage_path:
        return "unknown"
    if not storage.exists(storage_path):
        return "missing_file"
    try:
        on_disk = storage.size(storage_path)
    except (FileNotFoundError, OSError):
        return "unknown"
    if on_disk <= 0 or size_bytes <= 0:
        return "empty_file"
    try:
        data = storage.read_checkpoint(storage_path)
        if len(data) == 0:
            return "empty_file"
    except (FileNotFoundError, OSError):
        return "unknown"
    return "ok"


def _last_metric_timestamp_ms(conn: Any, run_id: str) -> int | None:
    row = conn.execute(
        """
        SELECT MAX(timestamp_ms) AS ts
        FROM metrics
        WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()
    if row is None or row["ts"] is None:
        return None
    return int(row["ts"])


def _latest_checkpoint_row(conn: Any, run_id: str) -> Any | None:
    return conn.execute(
        """
        SELECT * FROM checkpoints
        WHERE run_id = ?
        ORDER BY step DESC, created_at_ms DESC
        LIMIT 1
        """,
        (run_id,),
    ).fetchone()


def build_resume_snippet(
    *,
    project: str,
    run_name: str,
    api_key: str,
    base_url: str,
    checkpoint_step: int,
) -> str:
    return f'''import faultline

run = faultline.start(
    "{run_name}",
    project="{project}",
    api_key="{api_key}",
    base_url="{base_url}",
)

step = run.restore_latest(model=model, optimizer=optimizer)
# Resume training from step {{step}} (checkpoint saved at step {checkpoint_step})

for step in range(step, step + YOUR_TOTAL_STEPS):
    run.log(loss=loss, accuracy=accuracy)
    if step % 10 == 0:
        run.save(model=model, optimizer=optimizer, step=step)

run.complete()
'''


def build_inline_restore_snippet() -> str:
    return """state = run.load_latest_checkpoint_or_none()
if state:
    model.load_state_dict(state["model_state"])
    optimizer.load_state_dict(state["optimizer_state"])
    start_step = int(state.get("step", 0))
"""


def build_slurm_snippet(
    *,
    run_id: str,
    project: str,
    run_name: str,
    checkpoint_step: int,
) -> str:
    return f"""#!/bin/bash
#SBATCH --job-name=faultline-resume
#SBATCH --time=24:00:00
# Faultline resume template — adjust partition/account/modules for your cluster.

export FAULTLINE_API_KEY="${{FAULTLINE_API_KEY:-fl_dev_local}}"
export FAULTLINE_BASE_URL="${{FAULTLINE_BASE_URL:-http://127.0.0.1:8080}}"

# Run id: {run_id}
# Project / run: {project} / {run_name}
# Latest checkpoint step: {checkpoint_step}

python train.py \\
  --faultline-project "{project}" \\
  --faultline-run-name "{run_name}" \\
  --resume-from-checkpoint
"""


def compute_recovery_summary(
    conn: Any,
    run_row: Any,
    *,
    project_name: str,
    api_key: str = "fl_dev_local",
    base_url: str = "http://127.0.0.1:8080",
    storage: CloudCheckpointStorage | None = None,
) -> dict[str, Any]:
    run_id = str(run_row["id"])
    status = str(run_row["status"])
    latest_step = int(run_row["latest_step"])
    latest_checkpoint_step = int(run_row["latest_checkpoint_step"] or 0)
    checkpoint_storage = storage or get_checkpoint_storage()

    ckpt_row = _latest_checkpoint_row(conn, run_id)
    has_checkpoint = ckpt_row is not None
    latest_checkpoint: dict[str, Any] | None = None
    checkpoint_health: CheckpointHealth = "unknown"
    checkpoint_age_ms: int | None = None

    if ckpt_row is not None:
        latest_checkpoint = row_to_checkpoint(ckpt_row)
        checkpoint_health = check_checkpoint_health(
            checkpoint_storage,
            checkpoint_storage_path(ckpt_row),
            int(ckpt_row["size_bytes"]),
        )
        checkpoint_age_ms = max(0, now_ms() - int(ckpt_row["created_at_ms"]))

    effective_ckpt_step = (
        int(latest_checkpoint["step"]) if latest_checkpoint is not None else latest_checkpoint_step
    )
    estimated_lost_steps = 0
    if has_checkpoint and latest_step > effective_ckpt_step:
        estimated_lost_steps = latest_step - effective_ckpt_step
    elif not has_checkpoint and latest_step > 0:
        estimated_lost_steps = latest_step

    last_metric_at_ms = _last_metric_timestamp_ms(conn, run_id)
    now = now_ms()
    is_stale = (
        status == "running"
        and last_metric_at_ms is not None
        and (now - last_metric_at_ms) > STALE_RUN_THRESHOLD_MS
    )

    config_row = get_launch_config_row(conn, run_id)
    launch_config = (
        row_to_launch_config(config_row) if config_row is not None else None
    )
    last_resume = get_latest_resume_launch(conn, run_id)
    is_resuming = (
        last_resume is not None
        and last_resume["status"] == "started"
        and (now - int(last_resume["launched_at_ms"])) < 300_000
    )

    can_resume = (
        has_checkpoint
        and checkpoint_health == "ok"
        and launch_config is not None
        and status != "completed"
    )

    if status == "completed":
        recommendation: Recommendation = "run_completed"
        restore_status: RestoreStatus = "completed"
        recovery_badge: RecoveryBadge = "completed"
    elif not has_checkpoint:
        recommendation = "no_checkpoint"
        restore_status = "no_checkpoint"
        recovery_badge = "no_checkpoint"
    elif checkpoint_health != "ok":
        recommendation = "resume_from_checkpoint"
        restore_status = "unhealthy"
        recovery_badge = "checkpoint_missing"
    elif status == "running" and estimated_lost_steps == 0:
        recommendation = "resume_from_checkpoint"
        restore_status = "not_applicable"
        recovery_badge = "recoverable"
    elif status in ("failed", "stopped") or estimated_lost_steps > 0:
        recommendation = "resume_from_checkpoint"
        restore_status = "ready"
        recovery_badge = "recoverable"
    else:
        recommendation = "resume_from_checkpoint"
        restore_status = "ready"
        recovery_badge = "recoverable"

    if is_resuming:
        recovery_badge = "resuming"
    elif is_stale and status == "running":
        recovery_badge = "stale"

    display_status = _compute_display_status(
        status=status,
        is_stale=is_stale,
        is_resuming=is_resuming,
        recovery_badge=recovery_badge,
    )

    run_name = str(run_row["name"])
    resume_snippet = build_resume_snippet(
        project=project_name,
        run_name=run_name,
        api_key=api_key,
        base_url=base_url,
        checkpoint_step=effective_ckpt_step,
    )
    slurm_snippet = build_slurm_snippet(
        run_id=run_id,
        project=project_name,
        run_name=run_name,
        checkpoint_step=effective_ckpt_step,
    )

    return {
        "run_id": run_id,
        "project_name": project_name,
        "run_name": run_name,
        "status": status,
        "latest_step": latest_step,
        "latest_checkpoint_step": effective_ckpt_step,
        "estimated_lost_steps": estimated_lost_steps,
        "has_checkpoint": has_checkpoint,
        "latest_checkpoint": latest_checkpoint,
        "last_metric_at_ms": last_metric_at_ms,
        "checkpoint_age_ms": checkpoint_age_ms,
        "checkpoint_health": checkpoint_health,
        "restore_status": restore_status,
        "recovery_badge": recovery_badge,
        "recommendation": recommendation,
        "resume_snippet": resume_snippet,
        "inline_restore_snippet": build_inline_restore_snippet(),
        "slurm_snippet": slurm_snippet,
        "launch_config": launch_config,
        "last_resume": last_resume,
        "is_stale": is_stale,
        "display_status": display_status,
        "can_resume": can_resume,
    }


def _compute_display_status(
    *,
    status: str,
    is_stale: bool,
    is_resuming: bool,
    recovery_badge: str,
) -> str:
    if is_resuming:
        return "resuming"
    if is_stale:
        return "stale"
    if recovery_badge == "recoverable" and status in ("failed", "stopped"):
        return "recoverable"
    return status
