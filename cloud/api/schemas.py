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


class UserInfo(BaseModel):
    user_id: str
    email: str


class ApiKeyInfo(BaseModel):
    prefix: str
    created_at_ms: int


class MeResponse(BaseModel):
    user: UserInfo
    api_key: ApiKeyInfo
    usage: UsageResponse


class CreateApiKeyResponse(BaseModel):
    api_key: str
    prefix: str
    created_at_ms: int
    label: str


class CheckpointResponse(BaseModel):
    checkpoint_id: str
    run_id: str
    step: int
    size_bytes: int
    status: str
    metadata_json: str | None = None
    created_at_ms: int | None = None


class HealthResponse(BaseModel):
    status: str
    service: str = "faultline-cloud-api"
