"""
Faultline cloud ingestion API — projects, runs, metrics, events, checkpoints.
"""

from __future__ import annotations

import json
import os
import secrets
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Iterator

from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from cloud.api.auth import UserAuth, get_auth_context, get_current_user_id, get_user_auth
from cloud.api.checkpoints import (
    MAX_CHECKPOINT_BYTES,
    checkpoint_filename_for_step,
    checkpoint_storage_path,
    get_checkpoint_storage,
)
from cloud.api.storage import LocalCloudCheckpointStorage
from cloud.api.health_checks import health_payload, infrastructure_payload, ready_payload
from cloud.api.alerts import get_alert_settings, upsert_alert_settings
from cloud.api.worker import list_tasks, TASK_EVALUATE_ALERTS, enqueue_task
from cloud.api.db import (
    api_key_prefix,
    connect,
    get_or_create_project,
    get_user,
    init_db,
    list_api_keys,
    list_oauth_accounts,
    now_ms,
    row_to_api_key_list_item,
    row_to_checkpoint,
    row_to_run,
    get_user_by_oauth,
    upsert_oauth_account,
)
from cloud.api.oauth import exchange_code_for_profile, oauth_authorize_url
from cloud.api.launch_config import (
    get_launch_config_row,
    row_to_launch_config,
    upsert_launch_config,
    validate_launch_config_body,
)
from cloud.api.recovery import compute_recovery_summary
from cloud.api.resume_launcher import execute_resume
from cloud.api.schemas import (
    AuthLoginRequest,
    AlertSettingsRequest,
    AlertSettingsResponse,
    AuthMessageResponse,
    AuthSessionResponse,
    AuthSignupRequest,
    ConnectedAccount,
    BackgroundTaskResponse,
    InfrastructureResponse,
    ApiKeyInfo,
    ApiKeyListItem,
    CheckpointResponse,
    CreateApiKeyRequest,
    CreateApiKeyResponse,
    EventResponse,
    HealthResponse,
    LaunchConfigRequest,
    LaunchConfigResponse,
    LogEventRequest,
    LogMetricsRequest,
    MeResponse,
    OAuthCallbackRequest,
    OAuthStartResponse,
    MetricPointResponse,
    RecoveryResponse,
    ReadyResponse,
    ResumeResponse,
    RecoveryStatsResponse,
    RunResponse,
    StartRunRequest,
    UsageResponse,
    UserInfo,
)
from cloud.api.user_accounts import (
    create_user_with_password,
    get_or_create_user_for_oauth,
    get_user_by_email,
    normalize_email,
)
from cloud.api.passwords import verify_password
from cloud.api.sessions import (
    SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
    create_access_token,
)

from cloud.api.usage import get_usage, increment_usage
from cloud.api.env_validation import is_production, should_auto_create_schema, validate_startup_config
from cloud.api.migrations import verify_migrations_at_head
from cloud.api.rate_limit import RateLimitMiddleware

STATIC_DIR = Path(__file__).resolve().parent / "static"

from cloud.api.run_events import RUN_STATUS_EVENTS, log_run_event


def _cors_origins() -> list[str]:
    raw = os.environ.get("FAULTLINE_CORS_ORIGINS", "")
    defaults = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    if not raw.strip():
        return defaults
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def _session_cookie_kwargs() -> dict[str, Any]:
    secure_env = os.environ.get("FAULTLINE_COOKIE_SECURE", "").lower()
    secure = secure_env in ("1", "true", "yes")
    if not secure and os.environ.get("FAULTLINE_ENV", "").lower() == "production":
        secure = True
    return {
        "key": SESSION_COOKIE_NAME,
        "httponly": True,
        "samesite": "lax",
        "max_age": SESSION_TTL_SECONDS,
        "path": "/",
        "secure": secure,
    }


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(value=token, **_session_cookie_kwargs())


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")


def _auth_session_response(user_row: Any, *, include_token: bool = False) -> AuthSessionResponse:
    token = create_access_token(str(user_row["id"]), str(user_row["email"])) if include_token else None
    return AuthSessionResponse(
        user_id=str(user_row["id"]),
        email=str(user_row["email"]),
        created_at_ms=int(user_row["created_at_ms"]),
        access_token=token,
    )


@asynccontextmanager
async def lifespan(_app: FastAPI) -> Iterator[None]:
    validate_startup_config()
    if is_production():
        verify_migrations_at_head()
    if should_auto_create_schema():
        conn = connect()
        try:
            init_db(conn)
        finally:
            conn.close()
    from cloud.api.demo_seed import seed_demo_data, should_seed_demo

    if should_seed_demo():
        try:
            seed_demo_data()
        except Exception as error:
            import logging

            logging.getLogger("faultline").warning("demo seed failed: %s", error)
    from cloud.api.worker import start_worker

    start_worker()
    yield


def create_app() -> FastAPI:
    application = FastAPI(
        title="Faultline Cloud API",
        version="24.0",
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(RateLimitMiddleware)

    @application.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(**health_payload())

    @application.get("/ready", response_model=ReadyResponse)
    def ready() -> JSONResponse:
        payload = ready_payload()
        code = 200 if payload["ready"] else 503
        return JSONResponse(content=payload, status_code=code)

    @application.get("/v1/infrastructure", response_model=InfrastructureResponse)
    def infrastructure(
        auth: UserAuth = Depends(get_user_auth),
    ) -> InfrastructureResponse:
        del auth
        return InfrastructureResponse(**infrastructure_payload())

    @application.get("/v1/alert-settings", response_model=AlertSettingsResponse)
    def get_user_alert_settings(
        auth: UserAuth = Depends(get_user_auth),
    ) -> AlertSettingsResponse:
        conn = connect()
        try:
            return AlertSettingsResponse(**get_alert_settings(conn, auth.user_id))
        finally:
            conn.close()

    @application.put("/v1/alert-settings", response_model=AlertSettingsResponse)
    def update_alert_settings(
        body: AlertSettingsRequest,
        auth: UserAuth = Depends(get_user_auth),
    ) -> AlertSettingsResponse:
        conn = connect()
        try:
            settings = upsert_alert_settings(
                conn,
                auth.user_id,
                alert_email=body.alert_email,
                discord_webhook_url=body.discord_webhook_url,
                slack_webhook_url=body.slack_webhook_url,
            )
            return AlertSettingsResponse(**settings)
        finally:
            conn.close()

    @application.get("/v1/tasks", response_model=list[BackgroundTaskResponse])
    def list_background_tasks(
        auth: UserAuth = Depends(get_user_auth),
        limit: int = Query(default=20, ge=1, le=100),
    ) -> list[BackgroundTaskResponse]:
        conn = connect()
        try:
            tasks = list_tasks(conn, auth.user_id, limit=limit)
            return [BackgroundTaskResponse(**task) for task in tasks]
        finally:
            conn.close()

    @application.post("/v1/alerts/evaluate")
    def evaluate_alerts_now(
        auth: UserAuth = Depends(get_user_auth),
        background: bool = Query(default=True),
    ) -> dict[str, Any]:
        if background:
            task_id = enqueue_task(
                TASK_EVALUATE_ALERTS,
                {},
                user_id=auth.user_id,
            )
            return {"status": "queued", "task_id": task_id}
        conn = connect()
        try:
            from cloud.api.alerts import evaluate_user_alerts

            sent = evaluate_user_alerts(conn, auth.user_id)
            return {"status": "completed", "alerts_sent": len(sent), "details": sent}
        finally:
            conn.close()

    @application.get("/", response_class=FileResponse)
    def landing() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @application.get("/getting-started", response_class=FileResponse)
    def getting_started() -> FileResponse:
        return FileResponse(STATIC_DIR / "getting-started.html")

    @application.post("/v1/auth/signup", response_model=AuthSessionResponse)
    def auth_signup(body: AuthSignupRequest, response: Response) -> AuthSessionResponse:
        conn = connect()
        try:
            try:
                row = create_user_with_password(conn, body.email, body.password)
            except ValueError as error:
                detail = str(error)
                code = 409 if "already registered" in detail else 400
                raise HTTPException(status_code=code, detail=detail) from error
            payload = _auth_session_response(row, include_token=True)
            assert payload.access_token is not None
            _set_session_cookie(response, payload.access_token)
            return payload
        finally:
            conn.close()

    @application.post("/v1/auth/login", response_model=AuthSessionResponse)
    def auth_login(body: AuthLoginRequest, response: Response) -> AuthSessionResponse:
        conn = connect()
        try:
            row = get_user_by_email(conn, body.email)
            if row is None or not verify_password(body.password, str(row["password_hash"] or "")):
                raise HTTPException(status_code=401, detail="invalid email or password")
            payload = _auth_session_response(row, include_token=True)
            assert payload.access_token is not None
            _set_session_cookie(response, payload.access_token)
            return payload
        finally:
            conn.close()

    @application.post("/v1/auth/logout", response_model=AuthMessageResponse)
    def auth_logout(response: Response) -> AuthMessageResponse:
        _clear_session_cookie(response)
        return AuthMessageResponse()

    @application.get("/v1/auth/me", response_model=AuthSessionResponse)
    def auth_me(auth: UserAuth = Depends(get_user_auth)) -> AuthSessionResponse:
        conn = connect()
        try:
            row = get_user(conn, auth.user_id)
            if row is None:
                raise HTTPException(status_code=404, detail="user not found")
            return _auth_session_response(row)
        finally:
            conn.close()

    @application.get("/v1/auth/providers", response_model=list[ConnectedAccount])
    def auth_connected_providers(
        auth: UserAuth = Depends(get_user_auth),
    ) -> list[ConnectedAccount]:
        conn = connect()
        try:
            rows = list_oauth_accounts(conn, auth.user_id)
            return [
                ConnectedAccount(
                    provider=str(row["provider"]),
                    provider_email=str(row["provider_email"]) if row["provider_email"] else None,
                    linked_at_ms=int(row["linked_at_ms"]),
                    last_login_at_ms=int(row["last_login_at_ms"]),
                )
                for row in rows
            ]
        finally:
            conn.close()

    @application.get("/v1/auth/oauth/{provider}/start", response_model=OAuthStartResponse)
    def auth_oauth_start(
        provider: str,
        redirect_uri: str = Query(..., min_length=8),
        state: str = Query(..., min_length=8),
    ) -> OAuthStartResponse:
        if provider not in ("google", "github"):
            raise HTTPException(status_code=404, detail="unsupported oauth provider")
        try:
            authorize_url = oauth_authorize_url(provider, redirect_uri=redirect_uri, state=state)
        except RuntimeError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        return OAuthStartResponse(provider=provider, authorize_url=authorize_url)

    @application.post("/v1/auth/oauth/{provider}/callback", response_model=AuthSessionResponse)
    def auth_oauth_callback(
        provider: str,
        body: OAuthCallbackRequest,
        response: Response,
    ) -> AuthSessionResponse:
        if provider not in ("google", "github"):
            raise HTTPException(status_code=404, detail="unsupported oauth provider")
        try:
            profile = exchange_code_for_profile(
                provider,
                code=body.code,
                redirect_uri=body.redirect_uri,
            )
        except Exception as error:  # noqa: BLE001
            raise HTTPException(status_code=401, detail=f"oauth exchange failed: {error}") from error

        conn = connect()
        try:
            existing = get_user_by_oauth(conn, profile.provider, profile.provider_user_id)
            try:
                row = existing or get_or_create_user_for_oauth(
                    conn,
                    email=profile.email,
                    provider=profile.provider,
                )
            except ValueError as error:
                raise HTTPException(status_code=400, detail=str(error)) from error
            upsert_oauth_account(
                conn,
                user_id=str(row["id"]),
                provider=profile.provider,
                provider_user_id=profile.provider_user_id,
                provider_email=profile.email,
            )
            conn.commit()
            payload = _auth_session_response(row, include_token=True)
            assert payload.access_token is not None
            _set_session_cookie(response, payload.access_token)
            return payload
        finally:
            conn.close()

    @application.get("/v1/me", response_model=MeResponse)
    def me(auth: UserAuth = Depends(get_user_auth)) -> MeResponse:
        conn = connect()
        try:
            user_row = get_user(conn, auth.user_id)
            if user_row is None:
                raise HTTPException(status_code=404, detail="user not found")
            usage = get_usage(conn, auth.user_id)
            if auth.method == "api_key":
                usage["api_key_prefix"] = auth.key_prefix
            api_key_info = None
            if auth.method == "api_key" and auth.key_prefix and auth.key_created_at_ms:
                api_key_info = ApiKeyInfo(
                    prefix=auth.key_prefix,
                    created_at_ms=auth.key_created_at_ms,
                )
            return MeResponse(
                user=UserInfo(
                    user_id=auth.user_id,
                    email=str(user_row["email"]),
                ),
                api_key=api_key_info,
                usage=UsageResponse(**usage),
            )
        finally:
            conn.close()

    @application.get("/v1/usage", response_model=UsageResponse)
    def usage_totals(
        auth: UserAuth = Depends(get_user_auth),
    ) -> UsageResponse:
        conn = connect()
        try:
            usage = get_usage(conn, auth.user_id)
            if auth.method == "api_key":
                usage["api_key_prefix"] = auth.key_prefix
            return UsageResponse(**usage)
        finally:
            conn.close()

    @application.get("/v1/recovery/stats", response_model=RecoveryStatsResponse)
    def recovery_stats(
        auth: UserAuth = Depends(get_user_auth),
    ) -> RecoveryStatsResponse:
        conn = connect()
        try:
            rows = conn.execute(
                """
                SELECT r.id, r.latest_step, r.latest_checkpoint_step
                FROM runs r
                JOIN projects p ON p.id = r.project_id
                WHERE p.user_id = ? AND (r.status = 'failed' OR r.status = 'stopped')
                """,
                (auth.user_id,),
            ).fetchall()
            lost_steps = [max(0, int(row["latest_step"]) - int(row["latest_checkpoint_step"] or 0)) for row in rows]
            avg_lost = (sum(lost_steps) / len(lost_steps)) if lost_steps else 0.0
            resume_rows = conn.execute(
                """
                SELECT rl.status, rl.launched_at_ms
                FROM run_resume_launches rl
                JOIN runs r ON r.id = rl.run_id
                JOIN projects p ON p.id = r.project_id
                WHERE p.user_id = ?
                ORDER BY rl.launched_at_ms DESC
                """,
                (auth.user_id,),
            ).fetchall()
            successful = sum(1 for row in resume_rows if str(row["status"]) in ("started", "completed"))
            latest_latency = None
            latest_resume = resume_rows[0] if resume_rows else None
            if latest_resume is not None:
                latest_latency = max(0, now_ms() - int(latest_resume["launched_at_ms"]))
            avoided = sum(max(0, int(row["latest_checkpoint_step"] or 0)) for row in rows)
            return RecoveryStatsResponse(
                avg_lost_steps=round(avg_lost, 2),
                successful_resumes=successful,
                latest_recovery_latency_ms=latest_latency,
                time_lost_avoided_steps=avoided,
            )
        finally:
            conn.close()

    @application.get("/v1/api-keys", response_model=list[ApiKeyListItem])
    def list_user_api_keys(
        auth: UserAuth = Depends(get_user_auth),
    ) -> list[ApiKeyListItem]:
        conn = connect()
        try:
            rows = list_api_keys(conn, auth.user_id)
            return [
                ApiKeyListItem(**row_to_api_key_list_item(row)) for row in rows
            ]
        finally:
            conn.close()

    @application.post("/v1/api-keys", response_model=CreateApiKeyResponse)
    def create_api_key(
        auth: UserAuth = Depends(get_user_auth),
        label: str | None = Query(default=None),
        body: CreateApiKeyRequest | None = Body(default=None),
    ) -> CreateApiKeyResponse:
        """Create an API key for the current user. Full key returned once."""
        resolved_label = (
            (body.label if body and body.label else None)
            or label
            or "dev-key"
        ).strip()
        if not resolved_label:
            raise HTTPException(status_code=400, detail="label is required")

        key_value = f"fl_{secrets.token_urlsafe(24)}"
        created = now_ms()
        conn = connect()
        try:
            conn.execute(
                """
                INSERT INTO api_keys (id, user_id, key_value, label, created_at_ms)
                VALUES (?, ?, ?, ?, ?)
                """,
                (str(uuid.uuid4()), auth.user_id, key_value, resolved_label, created),
            )
            conn.commit()
        finally:
            conn.close()

        return CreateApiKeyResponse(
            api_key=key_value,
            prefix=api_key_prefix(key_value),
            created_at_ms=created,
            label=resolved_label,
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

    @application.get("/v1/runs/{run_id}/recovery", response_model=RecoveryResponse)
    def get_run_recovery(
        run_id: str,
        user_id: str = Depends(get_current_user_id),
        base_url: str = Query(default="http://127.0.0.1:8080"),
    ) -> RecoveryResponse:
        conn = connect()
        try:
            row = _fetch_run_for_user(conn, user_id, run_id)
            summary = compute_recovery_summary(
                conn,
                row,
                project_name=str(row["project_name"]),
                base_url=base_url.rstrip("/"),
            )
            return RecoveryResponse(**summary)
        finally:
            conn.close()

    @application.post("/v1/runs/{run_id}/launch-config", response_model=LaunchConfigResponse)
    def register_launch_config(
        run_id: str,
        body: LaunchConfigRequest,
        user_id: str = Depends(get_current_user_id),
    ) -> LaunchConfigResponse:
        conn = connect()
        try:
            _fetch_run_for_user(conn, user_id, run_id)
            normalized = validate_launch_config_body(body.model_dump(exclude_none=True))
            upsert_launch_config(conn, run_id, normalized)
            row = get_launch_config_row(conn, run_id)
            assert row is not None
            return LaunchConfigResponse(**row_to_launch_config(row))
        finally:
            conn.close()

    @application.get("/v1/runs/{run_id}/launch-config", response_model=LaunchConfigResponse)
    def get_launch_config(
        run_id: str,
        user_id: str = Depends(get_current_user_id),
    ) -> LaunchConfigResponse:
        conn = connect()
        try:
            _fetch_run_for_user(conn, user_id, run_id)
            row = get_launch_config_row(conn, run_id)
            if row is None:
                raise HTTPException(status_code=404, detail="no launch config for run")
            return LaunchConfigResponse(**row_to_launch_config(row))
        finally:
            conn.close()

    @application.post("/v1/runs/{run_id}/resume", response_model=ResumeResponse)
    def resume_run(
        run_id: str,
        user_id: str = Depends(get_current_user_id),
        background: bool = Query(default=False),
    ) -> ResumeResponse:
        if background:
            from cloud.api.worker import TASK_RESUME_RUN, enqueue_task

            task_id = enqueue_task(
                TASK_RESUME_RUN,
                {"run_id": run_id},
                user_id=user_id,
            )
            return JSONResponse(
                content={"status": "queued", "task_id": task_id, "run_id": run_id}
            )

        conn = connect()
        try:
            row = _fetch_run_for_user(conn, user_id, run_id)
            result = execute_resume(
                conn,
                row,
                project_name=str(row["project_name"]),
                user_id=user_id,
                log_event_fn=log_run_event,
            )
            return ResumeResponse(**result)
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
            checkpoint_id = str(uuid.uuid4())
            storage = get_checkpoint_storage()
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
                legacy_path = stored.storage_path  # object key for minio/s3
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
                    metadata_json,
                    created,
                    stored.storage_backend,
                    stored.storage_path,
                    stored.checksum_sha256,
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
                checkpoint_bytes_uploaded=stored.size_bytes,
            )
            conn.commit()
            from cloud.api.worker import TASK_VERIFY_CHECKPOINT, enqueue_task

            enqueue_task(
                TASK_VERIFY_CHECKPOINT,
                {"checkpoint_id": checkpoint_id},
                user_id=user_id,
            )
            return CheckpointResponse(
                checkpoint_id=checkpoint_id,
                run_id=run_id,
                step=step,
                size_bytes=stored.size_bytes,
                status="committed",
                storage_backend=stored.storage_backend,
                storage_path=stored.storage_path,
                checksum_sha256=stored.checksum_sha256,
                created_at_ms=created,
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
    ) -> Response:
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
            return _checkpoint_download_response(row)
        finally:
            conn.close()

    @application.get("/v1/runs/{run_id}/checkpoints/{checkpoint_id}/download")
    def download_checkpoint(
        run_id: str,
        checkpoint_id: str,
        user_id: str = Depends(get_current_user_id),
    ) -> Response:
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
            return _checkpoint_download_response(row)
        finally:
            conn.close()

    @application.get("/dashboard")
    def dashboard() -> FileResponse:
        return FileResponse(STATIC_DIR / "dashboard.html")

    @application.get("/v1/demo/workspace")
    def public_demo_workspace(limit: int = Query(default=5, ge=1, le=20)) -> dict[str, Any]:
        conn = connect()
        try:
            demo = get_user_by_email(conn, "demo@faultline.local")
            if demo is None:
                return {"runs": [], "events": {}, "checkpoints": {}}
            rows = conn.execute(
                """
                SELECT r.*, p.name AS project_name
                FROM runs r
                JOIN projects p ON p.id = r.project_id
                WHERE p.user_id = ?
                ORDER BY r.updated_at_ms DESC
                LIMIT ?
                """,
                (str(demo["id"]), limit),
            ).fetchall()
            runs = [row_to_run(row, str(row["project_name"])) for row in rows]
            events: dict[str, list[dict[str, Any]]] = {}
            checkpoints: dict[str, list[dict[str, Any]]] = {}
            for run in runs:
                run_id = str(run["run_id"])
                erows = conn.execute(
                    """
                    SELECT id, run_id, event_type, level, message, timestamp_ms
                    FROM events WHERE run_id = ?
                    ORDER BY timestamp_ms DESC LIMIT 20
                    """,
                    (run_id,),
                ).fetchall()
                crows = conn.execute(
                    """
                    SELECT * FROM checkpoints
                    WHERE run_id = ?
                    ORDER BY step DESC, created_at_ms DESC LIMIT 20
                    """,
                    (run_id,),
                ).fetchall()
                events[run_id] = [
                    {
                        "event_id": str(row["id"]),
                        "run_id": str(row["run_id"]),
                        "event_type": str(row["event_type"]),
                        "level": str(row["level"]),
                        "message": str(row["message"]),
                        "timestamp_ms": int(row["timestamp_ms"]),
                    }
                    for row in erows
                ]
                checkpoints[run_id] = [row_to_checkpoint(row) for row in crows]
            return {"runs": runs, "events": events, "checkpoints": checkpoints}
        finally:
            conn.close()

    application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    return application


def _checkpoint_download_response(row: Any) -> Response:
    storage = get_checkpoint_storage()
    stored_path = checkpoint_storage_path(row)
    if not stored_path or not storage.exists(stored_path):
        raise HTTPException(status_code=404, detail="checkpoint file missing")
    data = storage.read_checkpoint(stored_path)
    filename = stored_path.rsplit("/", 1)[-1] if "/" in stored_path else stored_path
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
