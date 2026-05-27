"""Persist and validate run launch configuration (local / Slurm)."""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import HTTPException

from cloud.api.db import now_ms

LAUNCH_LOCAL = "local_command"
LAUNCH_SLURM = "slurm_script"


def validate_launch_config_body(body: dict[str, Any]) -> dict[str, Any]:
    launch_type = body.get("launch_type")
    if launch_type not in (LAUNCH_LOCAL, LAUNCH_SLURM):
        raise HTTPException(
            status_code=422,
            detail="launch_type must be 'local_command' or 'slurm_script'",
        )

    command = body.get("command")
    script_path = body.get("script_path")
    working_dir = body.get("working_dir")
    environment = body.get("environment") or body.get("environment_json")

    if launch_type == LAUNCH_LOCAL:
        if not command or not isinstance(command, list) or not all(
            isinstance(part, str) and part for part in command
        ):
            raise HTTPException(
                status_code=422,
                detail="local_command requires non-empty command: list[str]",
            )
        if script_path:
            raise HTTPException(
                status_code=422,
                detail="script_path is only valid for slurm_script",
            )
        command_json = json.dumps(command)
        script_path_val = None
    else:
        if not script_path or not isinstance(script_path, str) or not script_path.strip():
            raise HTTPException(
                status_code=422,
                detail="slurm_script requires script_path",
            )
        if command:
            raise HTTPException(
                status_code=422,
                detail="command is only valid for local_command",
            )
        command_json = None
        script_path_val = script_path.strip()

    if working_dir is not None and not isinstance(working_dir, str):
        raise HTTPException(status_code=422, detail="working_dir must be a string")
    if environment is not None and not isinstance(environment, dict):
        raise HTTPException(status_code=422, detail="environment must be a JSON object")

    env_json = json.dumps(environment) if environment else None

    return {
        "launch_type": launch_type,
        "command_json": command_json,
        "script_path": script_path_val,
        "working_dir": working_dir,
        "environment_json": env_json,
    }


def upsert_launch_config(conn: Any, run_id: str, normalized: dict[str, Any]) -> dict[str, Any]:
    created = now_ms()
    existing = conn.execute(
        "SELECT created_at_ms FROM run_launch_configs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if existing is not None:
        created = int(existing["created_at_ms"])
        conn.execute(
            """
            UPDATE run_launch_configs
            SET launch_type = ?, command_json = ?, script_path = ?,
                working_dir = ?, environment_json = ?, updated_at_ms = ?
            WHERE run_id = ?
            """,
            (
                normalized["launch_type"],
                normalized["command_json"],
                normalized["script_path"],
                normalized["working_dir"],
                normalized["environment_json"],
                now_ms(),
                run_id,
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO run_launch_configs (
                run_id, launch_type, command_json, script_path,
                working_dir, environment_json, created_at_ms, updated_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                normalized["launch_type"],
                normalized["command_json"],
                normalized["script_path"],
                normalized["working_dir"],
                normalized["environment_json"],
                created,
                created,
            ),
        )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM run_launch_configs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    assert row is not None
    return row_to_launch_config(row)


def get_launch_config_row(conn: Any, run_id: str) -> Any | None:
    return conn.execute(
        "SELECT * FROM run_launch_configs WHERE run_id = ?",
        (run_id,),
    ).fetchone()


def row_to_launch_config(row: Any) -> dict[str, Any]:
    command = json.loads(row["command_json"]) if row["command_json"] else None
    environment = (
        json.loads(row["environment_json"]) if row["environment_json"] else None
    )
    return {
        "run_id": str(row["run_id"]),
        "launch_type": str(row["launch_type"]),
        "command": command,
        "script_path": row["script_path"],
        "working_dir": row["working_dir"],
        "environment": environment,
        "created_at_ms": int(row["created_at_ms"]),
        "updated_at_ms": int(row["updated_at_ms"]),
    }


def insert_resume_launch(
    conn: Any,
    run_id: str,
    *,
    launch_type: str,
    status: str,
    pid: int | None = None,
    slurm_job_id: str | None = None,
    command_json: str | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    launch_id = str(uuid.uuid4())
    launched_at = now_ms()
    conn.execute(
        """
        INSERT INTO run_resume_launches (
            id, run_id, launch_type, pid, slurm_job_id, command_json,
            launched_at_ms, status, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            launch_id,
            run_id,
            launch_type,
            pid,
            slurm_job_id,
            command_json,
            launched_at,
            status,
            error_message,
        ),
    )
    return {
        "launch_id": launch_id,
        "launched_at_ms": launched_at,
    }


def get_latest_resume_launch(conn: Any, run_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT * FROM run_resume_launches
        WHERE run_id = ?
        ORDER BY launched_at_ms DESC
        LIMIT 1
        """,
        (run_id,),
    ).fetchone()
    if row is None:
        return None
    command = json.loads(row["command_json"]) if row["command_json"] else None
    return {
        "launch_id": str(row["id"]),
        "run_id": str(row["run_id"]),
        "launch_type": str(row["launch_type"]),
        "pid": row["pid"],
        "slurm_job_id": row["slurm_job_id"],
        "command": command,
        "launched_at_ms": int(row["launched_at_ms"]),
        "status": str(row["status"]),
        "error_message": row["error_message"],
    }
