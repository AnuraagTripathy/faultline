"""Manual/API-triggered job relaunch for cloud runs (v17.2)."""

from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Any

from fastapi import HTTPException

from cloud.api.launch_config import (
    LAUNCH_LOCAL,
    LAUNCH_SLURM,
    get_launch_config_row,
    insert_resume_launch,
    row_to_launch_config,
)
from cloud.api.recovery import compute_recovery_summary

RESUME_REQUESTED = "faultline.run.resume_requested"
RESUME_STARTED = "faultline.run.resume_started"
RESUME_FAILED = "faultline.run.resume_failed"


def _parse_slurm_job_id(stdout: str) -> str | None:
    match = re.search(r"Submitted batch job (\d+)", stdout)
    if match:
        return match.group(1)
    return None


def launch_local_command(
    command: list[str],
    *,
    working_dir: str | None,
    environment: dict[str, str] | None,
) -> tuple[int | None, str | None]:
    """Start local process; returns (pid, error_message)."""
    env = os.environ.copy()
    if environment:
        env.update({str(k): str(v) for k, v in environment.items()})
    cwd = working_dir if working_dir else None
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
        )
        return process.pid, None
    except OSError as error:
        return None, str(error)


def launch_slurm_script(
    script_path: str,
    *,
    working_dir: str | None,
    environment: dict[str, str] | None,
) -> tuple[str | None, str | None]:
    """Submit Slurm job; returns (job_id, error_message)."""
    env = os.environ.copy()
    if environment:
        env.update({str(k): str(v) for k, v in environment.items()})
    cwd = working_dir if working_dir else None
    try:
        result = subprocess.run(
            ["sbatch", script_path],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        return None, str(error)

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "sbatch failed").strip()
        return None, detail

    job_id = _parse_slurm_job_id(result.stdout or "")
    if job_id is None:
        return None, f"sbatch succeeded but could not parse job id: {result.stdout!r}"
    return job_id, None


def execute_resume(
    conn: Any,
    run_row: Any,
    *,
    project_name: str,
    user_id: str,
    log_event_fn: Any,
) -> dict[str, Any]:
    """
    Validate and relaunch a failed/stopped run. Does not auto-retry.

    ``log_event_fn(conn, run_id, user_id, event_type, level, message)`` is injected
  for tests and to avoid circular imports with app.py.
    """
    run_id = str(run_row["id"])
    recovery = compute_recovery_summary(
        conn, run_row, project_name=project_name
    )

    if not recovery["has_checkpoint"]:
        raise HTTPException(status_code=400, detail="no checkpoint to resume from")
    if recovery["checkpoint_health"] != "ok":
        raise HTTPException(
            status_code=400,
            detail=f"checkpoint unhealthy: {recovery['checkpoint_health']}",
        )

    config_row = get_launch_config_row(conn, run_id)
    if config_row is None:
        raise HTTPException(
            status_code=400,
            detail="no launch config registered for this run",
        )
    launch_config = row_to_launch_config(config_row)

    log_event_fn(
        conn,
        run_id,
        user_id,
        RESUME_REQUESTED,
        "info",
        f"resume requested (checkpoint step {recovery['latest_checkpoint_step']})",
    )

    launch_type = launch_config["launch_type"]
    pid: int | None = None
    slurm_job_id: str | None = None
    command_json: str | None = config_row["command_json"]
    error: str | None = None

    if launch_type == LAUNCH_LOCAL:
        command = launch_config["command"]
        assert command is not None
        pid, error = launch_local_command(
            command,
            working_dir=launch_config.get("working_dir"),
            environment=launch_config.get("environment"),
        )
    elif launch_type == LAUNCH_SLURM:
        script_path = launch_config["script_path"]
        assert script_path is not None
        slurm_job_id, error = launch_slurm_script(
            script_path,
            working_dir=launch_config.get("working_dir"),
            environment=launch_config.get("environment"),
        )
    else:
        error = f"unsupported launch_type: {launch_type}"

    launched_at_ms = insert_resume_launch(
        conn,
        run_id,
        launch_type=launch_type,
        status="started" if error is None else "failed",
        pid=pid,
        slurm_job_id=slurm_job_id,
        command_json=command_json,
        error_message=error,
    )["launched_at_ms"]

    if error is not None:
        log_event_fn(
            conn,
            run_id,
            user_id,
            RESUME_FAILED,
            "error",
            error,
        )
        raise HTTPException(status_code=500, detail=error)

    log_event_fn(
        conn,
        run_id,
        user_id,
        RESUME_STARTED,
        "info",
        _resume_started_message(launch_type, pid=pid, slurm_job_id=slurm_job_id),
    )

    return {
        "status": "resume_started",
        "launch_type": launch_type,
        "pid": pid,
        "slurm_job_id": slurm_job_id,
        "checkpoint_step": recovery["latest_checkpoint_step"],
        "estimated_lost_steps": recovery["estimated_lost_steps"],
        "launched_at_ms": launched_at_ms,
        "command": launch_config.get("command"),
        "script_path": launch_config.get("script_path"),
    }


def _resume_started_message(
    launch_type: str,
    *,
    pid: int | None,
    slurm_job_id: str | None,
) -> str:
    if launch_type == LAUNCH_LOCAL and pid is not None:
        return f"resume started (local pid {pid})"
    if launch_type == LAUNCH_SLURM and slurm_job_id is not None:
        return f"resume started (slurm job {slurm_job_id})"
    return "resume started"
