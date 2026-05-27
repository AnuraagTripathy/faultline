"""Initial Faultline Cloud schema (v24).

Revision ID: 24_001
Revises:
Create Date: 2026-05-27

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "24_001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text()),
        sa.Column("auth_provider", sa.Text()),
        sa.Column("created_at_ms", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("key_value", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("created_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("last_used_at_ms", sa.BigInteger()),
        sa.UniqueConstraint("key_value", name="uq_api_keys_key_value"),
    )
    op.create_table(
        "projects",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at_ms", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("user_id", "name", name="uq_projects_user_name"),
    )
    op.create_table(
        "runs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("project_id", sa.Text(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("tags_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("latest_step", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latest_loss", sa.Float()),
        sa.Column("latest_checkpoint_step", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("updated_at_ms", sa.BigInteger(), nullable=False),
    )
    op.create_index("idx_runs_project", "runs", ["project_id"])
    op.create_table(
        "metrics",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("step", sa.Integer(), nullable=False),
        sa.Column("metrics_json", sa.Text(), nullable=False),
        sa.Column("timestamp_ms", sa.BigInteger(), nullable=False),
    )
    op.create_index("idx_metrics_run", "metrics", ["run_id", "step"])
    op.create_table(
        "events",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("level", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("timestamp_ms", sa.BigInteger(), nullable=False),
    )
    op.create_index("idx_events_run", "events", ["run_id", "timestamp_ms"])
    op.create_table(
        "usage_counters",
        sa.Column("user_id", sa.Text(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("runs_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metric_points_ingested", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("events_ingested", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("checkpoints_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("checkpoint_bytes_uploaded", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("last_used_at_ms", sa.BigInteger()),
    )
    op.create_table(
        "checkpoints",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("step", sa.Integer(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.Text()),
        sa.Column("created_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("storage_backend", sa.Text(), nullable=False, server_default="local"),
        sa.Column("storage_path", sa.Text()),
        sa.Column("checksum_sha256", sa.Text()),
    )
    op.create_index("idx_checkpoints_run", "checkpoints", ["run_id", "step"])
    op.create_table(
        "run_launch_configs",
        sa.Column("run_id", sa.Text(), sa.ForeignKey("runs.id"), primary_key=True),
        sa.Column("launch_type", sa.Text(), nullable=False),
        sa.Column("command_json", sa.Text()),
        sa.Column("script_path", sa.Text()),
        sa.Column("working_dir", sa.Text()),
        sa.Column("environment_json", sa.Text()),
        sa.Column("created_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("updated_at_ms", sa.BigInteger(), nullable=False),
    )
    op.create_table(
        "run_resume_launches",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("launch_type", sa.Text(), nullable=False),
        sa.Column("pid", sa.Integer()),
        sa.Column("slurm_job_id", sa.Text()),
        sa.Column("command_json", sa.Text()),
        sa.Column("launched_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error_message", sa.Text()),
    )
    op.create_index(
        "idx_resume_launches_run",
        "run_resume_launches",
        ["run_id", "launched_at_ms"],
    )
    op.create_table(
        "user_alert_settings",
        sa.Column("user_id", sa.Text(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("alert_email", sa.Text()),
        sa.Column("discord_webhook_url", sa.Text()),
        sa.Column("slack_webhook_url", sa.Text()),
        sa.Column("updated_at_ms", sa.BigInteger(), nullable=False),
    )
    op.create_table(
        "background_tasks",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Text(), sa.ForeignKey("users.id")),
        sa.Column("task_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("result_json", sa.Text()),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("updated_at_ms", sa.BigInteger(), nullable=False),
    )
    op.create_index(
        "idx_background_tasks_status",
        "background_tasks",
        ["status", "created_at_ms"],
    )
    op.create_table(
        "alert_deliveries",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("run_id", sa.Text()),
        sa.Column("alert_type", sa.Text(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at_ms", sa.BigInteger(), nullable=False),
    )
    op.create_index(
        "idx_alert_deliveries_user",
        "alert_deliveries",
        ["user_id", "created_at_ms"],
    )
    op.create_table(
        "user_oauth_accounts",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_user_id", sa.Text(), nullable=False),
        sa.Column("provider_email", sa.Text()),
        sa.Column("linked_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("last_login_at_ms", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("provider", "provider_user_id", name="uq_oauth_provider_user"),
        sa.UniqueConstraint("user_id", "provider", name="uq_oauth_user_provider"),
    )


def downgrade() -> None:
    op.drop_table("user_oauth_accounts")
    op.drop_table("alert_deliveries")
    op.drop_table("background_tasks")
    op.drop_table("user_alert_settings")
    op.drop_table("run_resume_launches")
    op.drop_table("run_launch_configs")
    op.drop_table("checkpoints")
    op.drop_table("usage_counters")
    op.drop_table("events")
    op.drop_table("metrics")
    op.drop_table("runs")
    op.drop_table("projects")
    op.drop_table("api_keys")
    op.drop_table("users")
