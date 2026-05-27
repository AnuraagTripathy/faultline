export interface Run {
  run_id: string;
  project_name: string;
  run_name: string;
  status: string;
  tags: string[];
  latest_step: number;
  latest_loss: number | null;
  latest_checkpoint_step: number;
  created_at_ms: number;
  updated_at_ms: number;
}

export interface MetricPoint {
  run_id: string;
  step: number;
  timestamp_ms: number;
  metrics: Record<string, number>;
}

export interface Event {
  event_id: string;
  run_id: string;
  event_type: string;
  level: string;
  message: string;
  timestamp_ms: number;
}

export interface Checkpoint {
  checkpoint_id: string;
  run_id: string;
  step: number;
  size_bytes: number;
  status: string;
  metadata_json?: string | null;
  created_at_ms?: number | null;
  storage_backend?: string;
  storage_path?: string | null;
  checksum_sha256?: string | null;
}

export interface InfrastructureStatus {
  version: string;
  database: {
    kind: string;
    status: string;
    error?: string | null;
  };
  object_storage: {
    backend: string;
    status: string;
    error?: string | null;
  };
  background_worker: {
    status: string;
    running?: boolean;
    queue_size?: number;
    error?: string | null;
  };
}

export interface AlertSettings {
  user_id: string;
  alert_email?: string | null;
  discord_webhook_url?: string | null;
  slack_webhook_url?: string | null;
  updated_at_ms?: number | null;
}

export interface BackgroundTask {
  task_id: string;
  task_type: string;
  status: string;
  payload: Record<string, unknown>;
  result?: Record<string, unknown> | null;
  error_message?: string | null;
  created_at_ms: number;
  updated_at_ms: number;
}

export interface ApiKeyListItem {
  id: string;
  prefix: string;
  label: string;
  created_at_ms: number;
  last_used_at_ms: number | null;
}

export interface Usage {
  runs_created: number;
  metric_points_ingested: number;
  events_ingested: number;
  checkpoints_created: number;
  checkpoint_bytes_uploaded: number;
  last_used_at_ms: number | null;
  api_key_prefix?: string | null;
}

export interface UserInfo {
  user_id: string;
  email: string;
}

export interface ApiKeyInfo {
  prefix: string;
  created_at_ms: number;
}

export interface MeResponse {
  user: UserInfo;
  api_key?: ApiKeyInfo | null;
  usage: Usage;
}

export interface AuthSession {
  user_id: string;
  email: string;
  created_at_ms: number;
}

export interface ConnectedAccount {
  provider: "google" | "github" | string;
  provider_email?: string | null;
  linked_at_ms: number;
  last_login_at_ms: number;
}

export interface RecoveryStats {
  avg_lost_steps: number;
  successful_resumes: number;
  latest_recovery_latency_ms?: number | null;
  time_lost_avoided_steps: number;
}

export interface CreateApiKeyResponse {
  api_key: string;
  prefix: string;
  created_at_ms: number;
  label: string;
}

export interface LaunchConfig {
  run_id: string;
  launch_type: string;
  command?: string[] | null;
  script_path?: string | null;
  working_dir?: string | null;
  environment?: Record<string, string> | null;
  created_at_ms: number;
  updated_at_ms: number;
}

export interface ResumeLaunchInfo {
  launch_id: string;
  run_id: string;
  launch_type: string;
  pid?: number | null;
  slurm_job_id?: string | null;
  command?: string[] | null;
  launched_at_ms: number;
  status: string;
  error_message?: string | null;
}

export interface RecoverySummary {
  run_id: string;
  project_name: string;
  run_name: string;
  status: string;
  latest_step: number;
  latest_checkpoint_step: number;
  estimated_lost_steps: number;
  has_checkpoint: boolean;
  latest_checkpoint?: Checkpoint | null;
  last_metric_at_ms?: number | null;
  checkpoint_age_ms?: number | null;
  checkpoint_health: string;
  restore_status: string;
  recovery_badge: string;
  recommendation: string;
  resume_snippet: string;
  inline_restore_snippet: string;
  slurm_snippet: string;
  launch_config?: LaunchConfig | null;
  last_resume?: ResumeLaunchInfo | null;
  is_stale: boolean;
  display_status: string;
  can_resume: boolean;
}

export interface ResumeResponse {
  status: string;
  launch_type: string;
  pid?: number | null;
  slurm_job_id?: string | null;
  checkpoint_step: number;
  estimated_lost_steps: number;
  launched_at_ms: number;
  command?: string[] | null;
  script_path?: string | null;
}
