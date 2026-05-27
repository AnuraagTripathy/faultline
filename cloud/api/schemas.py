"""Request/response models for the cloud ingestion API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class StartRunRequest(BaseModel):
    project: str = Field(min_length=1)
    run_name: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)


class LogMetricsRequest(BaseModel):
    step: int = Field(ge=0)
    metrics: dict[str, float]


class LogEventRequest(BaseModel):
    event_type: str = Field(min_length=1)
    level: str = "info"
    message: str = ""


class RunResponse(BaseModel):
    run_id: str
    project_name: str
    run_name: str
    status: str
    tags: list[str]
    latest_step: int
    latest_loss: float | None
    latest_checkpoint_step: int = 0
    created_at_ms: int
    updated_at_ms: int


class MetricPointResponse(BaseModel):
    run_id: str
    step: int
    timestamp_ms: int
    metrics: dict[str, float]


class EventResponse(BaseModel):
    event_id: str
    run_id: str
    event_type: str
    level: str
    message: str
    timestamp_ms: int


class UsageResponse(BaseModel):
    runs_created: int
    metric_points_ingested: int
    events_ingested: int
    checkpoints_created: int
    checkpoint_bytes_uploaded: int
    last_used_at_ms: int | None = None
    api_key_prefix: str | None = None


class UserInfo(BaseModel):
    user_id: str
    email: str


class ApiKeyInfo(BaseModel):
    prefix: str
    created_at_ms: int


class MeResponse(BaseModel):
    user: UserInfo
    api_key: ApiKeyInfo | None = None
    usage: UsageResponse


class AuthSignupRequest(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=8)


class AuthLoginRequest(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=1)


class AuthSessionResponse(BaseModel):
    user_id: str
    email: str
    created_at_ms: int
    access_token: str | None = None


class ConnectedAccount(BaseModel):
    provider: str
    provider_email: str | None = None
    linked_at_ms: int
    last_login_at_ms: int


class OAuthStartResponse(BaseModel):
    provider: str
    authorize_url: str


class OAuthCallbackRequest(BaseModel):
    code: str = Field(min_length=3)
    redirect_uri: str = Field(min_length=8)


class RecoveryStatsResponse(BaseModel):
    avg_lost_steps: float
    successful_resumes: int
    latest_recovery_latency_ms: int | None = None
    time_lost_avoided_steps: int


class AuthMessageResponse(BaseModel):
    ok: bool = True
    message: str = "logged out"


class CreateApiKeyRequest(BaseModel):
    label: str | None = None


class CreateApiKeyResponse(BaseModel):
    api_key: str
    prefix: str
    created_at_ms: int
    label: str


class ApiKeyListItem(BaseModel):
    id: str
    prefix: str
    label: str
    created_at_ms: int
    last_used_at_ms: int | None = None


class CheckpointResponse(BaseModel):
    checkpoint_id: str
    run_id: str
    step: int
    size_bytes: int
    status: str
    metadata_json: str | None = None
    created_at_ms: int | None = None
    storage_backend: str = "local"
    storage_path: str | None = None
    checksum_sha256: str | None = None


class HealthResponse(BaseModel):
    status: str
    service: str = "faultline-cloud-api"
    version: str = "24.0"
    database: str = "unknown"
    database_kind: str = "unknown"
    checkpoints_storage: str = "unknown"
    storage_backend: str = "unknown"
    background_worker: str = "unknown"
    database_error: str | None = None
    checkpoints_error: str | None = None
    worker_error: str | None = None


class ReadyResponse(BaseModel):
    ready: bool
    status: str
    service: str = "faultline-cloud-api"
    version: str = "24.0"
    database: str = "unknown"
    database_error: str | None = None


class AlertSettingsRequest(BaseModel):
    alert_email: str | None = None
    discord_webhook_url: str | None = None
    slack_webhook_url: str | None = None


class AlertSettingsResponse(BaseModel):
    user_id: str
    alert_email: str | None = None
    discord_webhook_url: str | None = None
    slack_webhook_url: str | None = None
    updated_at_ms: int | None = None


class BackgroundTaskResponse(BaseModel):
    task_id: str
    task_type: str
    status: str
    payload: dict = Field(default_factory=dict)
    result: dict | None = None
    error_message: str | None = None
    created_at_ms: int
    updated_at_ms: int


class InfrastructureResponse(BaseModel):
    version: str
    database: dict
    object_storage: dict
    background_worker: dict


class LaunchConfigRequest(BaseModel):
    launch_type: str = Field(min_length=1)
    command: list[str] | None = None
    script_path: str | None = None
    working_dir: str | None = None
    environment: dict[str, str] | None = None


class LaunchConfigResponse(BaseModel):
    run_id: str
    launch_type: str
    command: list[str] | None = None
    script_path: str | None = None
    working_dir: str | None = None
    environment: dict[str, str] | None = None
    created_at_ms: int
    updated_at_ms: int


class ResumeLaunchInfo(BaseModel):
    launch_id: str
    run_id: str
    launch_type: str
    pid: int | None = None
    slurm_job_id: str | None = None
    command: list[str] | None = None
    launched_at_ms: int
    status: str
    error_message: str | None = None


class ResumeResponse(BaseModel):
    status: str
    launch_type: str
    pid: int | None = None
    slurm_job_id: str | None = None
    checkpoint_step: int
    estimated_lost_steps: int
    launched_at_ms: int
    command: list[str] | None = None
    script_path: str | None = None


class RecoveryResponse(BaseModel):
    run_id: str
    project_name: str
    run_name: str
    status: str
    latest_step: int
    latest_checkpoint_step: int
    estimated_lost_steps: int
    has_checkpoint: bool
    latest_checkpoint: CheckpointResponse | None = None
    last_metric_at_ms: int | None = None
    checkpoint_age_ms: int | None = None
    checkpoint_health: str
    restore_status: str
    recovery_badge: str
    recommendation: str
    resume_snippet: str
    inline_restore_snippet: str
    slurm_snippet: str
    launch_config: LaunchConfigResponse | None = None
    last_resume: ResumeLaunchInfo | None = None
    is_stale: bool = False
    display_status: str = "running"
    can_resume: bool = False
