"""
Faultline cloud ingestion API — projects, runs, metrics, events, checkpoints.
"""

from __future__ import annotations

import json
import secrets
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Iterator

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from cloud.api.auth import AuthContext, get_auth_context, get_current_user_id
from cloud.api.checkpoints import MAX_CHECKPOINT_BYTES, checkpoint_path
from cloud.api.db import (
    connect,
    get_or_create_project,
    get_user,
    init_db,
    now_ms,
    row_to_checkpoint,
    row_to_run,
)
from cloud.api.schemas import (
    ApiKeyInfo,
    CheckpointResponse,
    CreateApiKeyResponse,
    EventResponse,
    HealthResponse,
    LogEventRequest,
    LogMetricsRequest,
    MeResponse,
    MetricPointResponse,
    RunResponse,
    StartRunRequest,
    UsageResponse,
    UserInfo,
)
from cloud.api.usage import get_usage, increment_usage

STATIC_DIR = Path(__file__).resolve().parent / "static"

RUN_STATUS_EVENTS = {
    "faultline.run.completed": "completed",
    "faultline.run.failed": "failed",
    "faultline.run.stopped": "stopped",
}


@asynccontextmanager
async def lifespan(_app: FastAPI) -> Iterator[None]:
    conn = connect()
    try:
        init_db(conn)
    finally:
        conn.close()
    yield


def create_app() -> FastAPI:
    application = FastAPI(
        title="Faultline Cloud API",
        version="16.3",
        lifespan=lifespan,
    )

    @application.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @application.get("/", response_class=FileResponse)
    def landing() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @application.get("/getting-started", response_class=FileResponse)
    def getting_started() -> FileResponse:
        return FileResponse(STATIC_DIR / "getting-started.html")

    @application.get("/v1/me", response_model=MeResponse)
    def me(auth: AuthContext = Depends(get_auth_context)) -> MeResponse:
        conn = connect()
        try:
            user_row = get_user(conn, auth.user_id)
            if user_row is None:
                raise HTTPException(status_code=404, detail="user not found")
            usage = get_usage(conn, auth.user_id)
            return MeResponse(
                user=UserInfo(
                    user_id=auth.user_id,
                    email=str(user_row["email"]),
                ),
                api_key=ApiKeyInfo(
                    prefix=auth.key_prefix,
                    created_at_ms=auth.key_created_at_ms,
                ),
                usage=UsageResponse(**usage),
            )
        finally:
            conn.close()

    @application.get("/v1/usage", response_model=UsageResponse)
    def usage_totals(
        user_id: str = Depends(get_current_user_id),
    ) -> UsageResponse:
        conn = connect()
        try:
            return UsageResponse(**get_usage(conn, user_id))
        finally:
            conn.close()

    @application.post("/v1/api-keys", response_model=CreateApiKeyResponse)
    def create_api_key(
        auth: AuthContext = Depends(get_auth_context),
        label: str = Query(default="dev-key"),
    ) -> CreateApiKeyResponse:
        """Dev-only: create another plaintext API key for the current user."""
        key_value = f"fl_{secrets.token_urlsafe(24)}"
        created = now_ms()
        conn = connect()
        try:
            conn.execute(
                """
                INSERT INTO api_keys (id, user_id, key_value, label, created_at_ms)
                VALUES (?, ?, ?, ?, ?)
                """,
                (str(uuid.uuid4()), auth.user_id, key_value, label, created),
            )
            conn.commit()
        finally:
            conn.close()
        from cloud.api.db import api_key_prefix

        return CreateApiKeyResponse(
            api_key=key_value,
            prefix=api_key_prefix(key_value),
            created_at_ms=created,
            label=label,
        )

    @application.post("/v1/runs/start", response_model=RunResponse)
    def start_run(
        body: StartRunRequest,
        user_id: str = Depends(get_current_user_id),
    ) -> RunResponse:
        conn = connect()
        try:
            project_id = get_or_create_project(conn, user_id, body.project)
            run_id = str(uuid.uuid4())
            created = now_ms()
            conn.execute(
                """
                INSERT INTO runs (
                    id, project_id, name, status, tags_json,
                    latest_step, latest_loss, latest_checkpoint_step,
                    created_at_ms, updated_at_ms
                ) VALUES (?, ?, ?, 'running', ?, 0, NULL, 0, ?, ?)
                """,
                (
                    run_id,
                    project_id,
                    body.run_name,
                    json.dumps(body.tags),
                    created,
                    created,
                ),
            )
            increment_usage(conn, user_id, runs_created=1)
            conn.commit()
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            assert row is not None
            return RunResponse(**row_to_run(row, body.project))
        finally:
            conn.close()

    @application.get("/v1/runs", response_model=list[RunResponse])
    def list_runs(user_id: str = Depends(get_current_user_id)) -> list[RunResponse]:
        conn = connect()
        try:
            rows = conn.execute(
                """
                SELECT r.*, p.name AS project_name
                FROM runs r
                JOIN projects p ON p.id = r.project_id
                WHERE p.user_id = ?
                ORDER BY r.updated_at_ms DESC
                """,
                (user_id,),
            ).fetchall()
            return [
                RunResponse(**row_to_run(row, str(row["project_name"]))) for row in rows
            ]
        finally:
            conn.close()

    @application.get("/v1/runs/{run_id}", response_model=RunResponse)
    def get_run(
        run_id: str,
        user_id: str = Depends(get_current_user_id),
    ) -> RunResponse:
        conn = connect()
        try:
            row = _fetch_run_for_user(conn, user_id, run_id)
            return RunResponse(**row_to_run(row, str(row["project_name"])))
        finally:
            conn.close()

    @application.post("/v1/runs/{run_id}/metrics", response_model=RunResponse)
    def log_metrics(
        run_id: str,
        body: LogMetricsRequest,
        user_id: str = Depends(get_current_user_id),
    ) -> RunResponse:
        conn = connect()
        try:
            _fetch_run_for_user(conn, user_id, run_id)
            timestamp = now_ms()
            conn.execute(
                """
                INSERT INTO metrics (id, run_id, step, metrics_json, timestamp_ms)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    run_id,
                    body.step,
                    json.dumps(body.metrics),
                    timestamp,
                ),
            )
            latest_loss = body.metrics.get("loss")
            conn.execute(
                """
                UPDATE runs
                SET latest_step = ?, latest_loss = ?, updated_at_ms = ?
                WHERE id = ?
                """,
                (body.step, latest_loss, timestamp, run_id),
            )
            # One ingested point per POST (one step sample), not per metric key.
            increment_usage(conn, user_id, metric_points_ingested=1)
            conn.commit()
            row = conn.execute(
                """
                SELECT r.*, p.name AS project_name
                FROM runs r
                JOIN projects p ON p.id = r.project_id
                WHERE r.id = ?
                """,
                (run_id,),
            ).fetchone()
            assert row is not None
            return RunResponse(**row_to_run(row, str(row["project_name"])))
        finally:
            conn.close()

    @application.post("/v1/runs/{run_id}/events", response_model=RunResponse)
    def log_event(
        run_id: str,
        body: LogEventRequest,
        user_id: str = Depends(get_current_user_id),
    ) -> RunResponse:
        conn = connect()
        try:
            _fetch_run_for_user(conn, user_id, run_id)
            timestamp = now_ms()
            conn.execute(
                """
                INSERT INTO events (id, run_id, event_type, level, message, timestamp_ms)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    run_id,
                    body.event_type,
                    body.level.lower(),
                    body.message,
                    timestamp,
                ),
            )
            new_status = RUN_STATUS_EVENTS.get(body.event_type)
            if new_status is not None:
                conn.execute(
                    "UPDATE runs SET status = ?, updated_at_ms = ? WHERE id = ?",
                    (new_status, timestamp, run_id),
                )
            else:
                conn.execute(
                    "UPDATE runs SET updated_at_ms = ? WHERE id = ?",
                    (timestamp, run_id),
                )
            increment_usage(conn, user_id, events_ingested=1)
            conn.commit()
            row = conn.execute(
                """
                SELECT r.*, p.name AS project_name
                FROM runs r
                JOIN projects p ON p.id = r.project_id
                WHERE r.id = ?
                """,
                (run_id,),
            ).fetchone()
            assert row is not None
            return RunResponse(**row_to_run(row, str(row["project_name"])))
        finally:
            conn.close()

    @application.get(
        "/v1/runs/{run_id}/metrics",
        response_model=list[MetricPointResponse],
    )
    def list_metrics(
        run_id: str,
        limit: int = Query(default=1000, ge=1, le=10_000),
        user_id: str = Depends(get_current_user_id),
    ) -> list[MetricPointResponse]:
        conn = connect()
        try:
            _fetch_run_for_user(conn, user_id, run_id)
            rows = conn.execute(
                """
                SELECT run_id, step, metrics_json, timestamp_ms
                FROM metrics
                WHERE run_id = ?
                ORDER BY step ASC
                LIMIT ?
                """,
                (run_id, limit),
            ).fetchall()
            return [
                MetricPointResponse(
                    run_id=str(row["run_id"]),
                    step=int(row["step"]),
                    timestamp_ms=int(row["timestamp_ms"]),
                    metrics=json.loads(row["metrics_json"]),
                )
                for row in rows
            ]
        finally:
            conn.close()

    @application.get(
        "/v1/runs/{run_id}/events",
        response_model=list[EventResponse],
    )
    def list_events(
        run_id: str,
        limit: int = Query(default=100, ge=1, le=500),
        user_id: str = Depends(get_current_user_id),
    ) -> list[EventResponse]:
        conn = connect()
        try:
            _fetch_run_for_user(conn, user_id, run_id)
            rows = conn.execute(
                """
                SELECT id, run_id, event_type, level, message, timestamp_ms
                FROM events
                WHERE run_id = ?
                ORDER BY timestamp_ms DESC
                LIMIT ?
                """,
                (run_id, limit),
            ).fetchall()
            return [
                EventResponse(
                    event_id=str(row["id"]),
                    run_id=str(row["run_id"]),
                    event_type=str(row["event_type"]),
                    level=str(row["level"]),
                    message=str(row["message"]),
                    timestamp_ms=int(row["timestamp_ms"]),
                )
                for row in rows
            ]
        finally:
            conn.close()

    @application.post(
        "/v1/runs/{run_id}/checkpoints",
        response_model=CheckpointResponse,
    )
    async def upload_checkpoint(
        run_id: str,
        step: int = Form(...),
        file: UploadFile = File(...),
        metadata_json: str | None = Form(None),
        user_id: str = Depends(get_current_user_id),
    ) -> CheckpointResponse:
        conn = connect()
        try:
            _fetch_run_for_user(conn, user_id, run_id)
            payload = await file.read()
            size_bytes = len(payload)
            if size_bytes > MAX_CHECKPOINT_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"checkpoint exceeds {MAX_CHECKPOINT_BYTES} byte limit",
                )
            path = checkpoint_path(user_id, run_id, step)
            path.write_bytes(payload)
            checkpoint_id = str(uuid.uuid4())
            created = now_ms()
            conn.execute(
                """
                INSERT INTO checkpoints (
                    id, run_id, step, size_bytes, path, status,
                    metadata_json, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, 'committed', ?, ?)
                """,
                (
                    checkpoint_id,
                    run_id,
                    step,
                    size_bytes,
                    str(path),
                    metadata_json,
                    created,
                ),
            )
            conn.execute(
                """
                UPDATE runs
                SET latest_checkpoint_step = CASE
                    WHEN latest_checkpoint_step < ? THEN ?
                    ELSE latest_checkpoint_step
                END,
                updated_at_ms = ?
                WHERE id = ?
                """,
                (step, step, created, run_id),
            )
            increment_usage(
                conn,
                user_id,
                checkpoints_created=1,
                checkpoint_bytes_uploaded=size_bytes,
            )
            conn.commit()
            return CheckpointResponse(
                checkpoint_id=checkpoint_id,
                run_id=run_id,
                step=step,
                size_bytes=size_bytes,
                status="committed",
            )
        finally:
            conn.close()

    @application.get(
        "/v1/runs/{run_id}/checkpoints",
        response_model=list[CheckpointResponse],
    )
    def list_checkpoints(
        run_id: str,
        user_id: str = Depends(get_current_user_id),
    ) -> list[CheckpointResponse]:
        conn = connect()
        try:
            _fetch_run_for_user(conn, user_id, run_id)
            rows = conn.execute(
                """
                SELECT * FROM checkpoints
                WHERE run_id = ?
                ORDER BY step DESC, created_at_ms DESC
                """,
                (run_id,),
            ).fetchall()
            return [CheckpointResponse(**row_to_checkpoint(row)) for row in rows]
        finally:
            conn.close()

    @application.get(
        "/v1/runs/{run_id}/checkpoints/latest",
        response_model=CheckpointResponse,
    )
    def latest_checkpoint(
        run_id: str,
        user_id: str = Depends(get_current_user_id),
    ) -> CheckpointResponse:
        conn = connect()
        try:
            _fetch_run_for_user(conn, user_id, run_id)
            row = conn.execute(
                """
                SELECT * FROM checkpoints
                WHERE run_id = ?
                ORDER BY step DESC, created_at_ms DESC
                LIMIT 1
                """,
                (run_id,),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="no checkpoints for run")
            return CheckpointResponse(**row_to_checkpoint(row))
        finally:
            conn.close()

    @application.get("/v1/runs/{run_id}/checkpoints/latest/download")
    def download_latest_checkpoint(
        run_id: str,
        user_id: str = Depends(get_current_user_id),
    ) -> FileResponse:
        conn = connect()
        try:
            _fetch_run_for_user(conn, user_id, run_id)
            row = conn.execute(
                """
                SELECT * FROM checkpoints
                WHERE run_id = ?
                ORDER BY step DESC, created_at_ms DESC
                LIMIT 1
                """,
                (run_id,),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="no checkpoints for run")
            path = Path(str(row["path"]))
            if not path.is_file():
                raise HTTPException(status_code=404, detail="checkpoint file missing")
            return FileResponse(
                path,
                media_type="application/octet-stream",
                filename=path.name,
            )
        finally:
            conn.close()

    @application.get("/v1/runs/{run_id}/checkpoints/{checkpoint_id}/download")
    def download_checkpoint(
        run_id: str,
        checkpoint_id: str,
        user_id: str = Depends(get_current_user_id),
    ) -> FileResponse:
        conn = connect()
        try:
            _fetch_run_for_user(conn, user_id, run_id)
            row = conn.execute(
                """
                SELECT * FROM checkpoints
                WHERE id = ? AND run_id = ?
                """,
                (checkpoint_id, run_id),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="unknown checkpoint")
            path = Path(str(row["path"]))
            if not path.is_file():
                raise HTTPException(status_code=404, detail="checkpoint file missing")
            return FileResponse(
                path,
                media_type="application/octet-stream",
                filename=path.name,
            )
        finally:
            conn.close()

    @application.get("/dashboard")
    def dashboard() -> FileResponse:
        return FileResponse(STATIC_DIR / "dashboard.html")

    application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    return application


def _fetch_run_for_user(
    conn: Any,
    user_id: str,
    run_id: str,
) -> Any:
    row = conn.execute(
        """
        SELECT r.*, p.name AS project_name
        FROM runs r
        JOIN projects p ON p.id = r.project_id
        WHERE r.id = ? AND p.user_id = ?
        """,
        (run_id, user_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"unknown run: {run_id}")
    return row


app = create_app()
