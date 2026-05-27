import type { Checkpoint, Event, MetricPoint, RecoverySummary, Run } from "./types";

export const DEMO_RUN_IDS = {
  running: "demo-run-running",
  failed: "demo-run-failed",
  completed: "demo-run-completed",
} as const;

const now = Date.now();

function metricsFor(steps: number[], lossFn: (s: number) => number): MetricPoint[] {
  return steps.map((step, i) => ({
    run_id: DEMO_RUN_IDS.running,
    step,
    timestamp_ms: now - (steps.length - i) * 60_000,
    metrics: { loss: lossFn(step), progress_pct: Math.min(100, step / 5) },
  }));
}

export const DEMO_RUNS: Run[] = [
  {
    run_id: DEMO_RUN_IDS.running,
    project_name: "faultline-demo",
    run_name: "resnet-finetune-live",
    status: "running",
    tags: ["integration:pytorch", "demo"],
    latest_step: 180,
    latest_loss: 0.42,
    latest_checkpoint_step: 160,
    created_at_ms: now - 3_600_000,
    updated_at_ms: now - 30_000,
  },
  {
    run_id: DEMO_RUN_IDS.failed,
    project_name: "faultline-demo",
    run_name: "slurm-protein-exp7",
    status: "failed",
    tags: ["integration:lightning", "hpc", "demo"],
    latest_step: 400,
    latest_loss: 0.18,
    latest_checkpoint_step: 400,
    created_at_ms: now - 86_400_000,
    updated_at_ms: now - 120_000,
  },
  {
    run_id: DEMO_RUN_IDS.completed,
    project_name: "faultline-demo",
    run_name: "llama-alpaca-finetune",
    status: "completed",
    tags: ["integration:huggingface", "demo"],
    latest_step: 500,
    latest_loss: 0.09,
    latest_checkpoint_step: 500,
    created_at_ms: now - 172_800_000,
    updated_at_ms: now - 3_600_000,
  },
];

export const DEMO_METRICS: Record<string, MetricPoint[]> = {
  [DEMO_RUN_IDS.running]: metricsFor(
    Array.from({ length: 46 }, (_, i) => i * 4),
    (s) => 2 * 0.98 ** s
  ),
  [DEMO_RUN_IDS.failed]: metricsFor(
    Array.from({ length: 81 }, (_, i) => i * 5),
    (s) => 1.5 / (1 + s * 0.01)
  ).map((p) => ({ ...p, run_id: DEMO_RUN_IDS.failed })),
  [DEMO_RUN_IDS.completed]: metricsFor(
    Array.from({ length: 51 }, (_, i) => i * 10),
    (s) => 0.8 * 0.995 ** s
  ).map((p) => ({ ...p, run_id: DEMO_RUN_IDS.completed })),
};

export const DEMO_CHECKPOINTS: Record<string, Checkpoint[]> = {
  [DEMO_RUN_IDS.running]: [
    {
      checkpoint_id: "cp-1",
      run_id: DEMO_RUN_IDS.running,
      step: 160,
      size_bytes: 48_000_000,
      status: "committed",
      created_at_ms: now - 90_000,
      storage_backend: "minio",
    },
  ],
  [DEMO_RUN_IDS.failed]: [100, 200, 300, 400].map((step, i) => ({
    checkpoint_id: `cp-f-${i}`,
    run_id: DEMO_RUN_IDS.failed,
    step,
    size_bytes: 120_000_000,
    status: "committed",
    created_at_ms: now - 600_000 + i * 1000,
    storage_backend: "minio",
  })),
  [DEMO_RUN_IDS.completed]: [
    {
      checkpoint_id: "cp-c-1",
      run_id: DEMO_RUN_IDS.completed,
      step: 500,
      size_bytes: 890_000_000,
      status: "committed",
      created_at_ms: now - 3_600_000,
      storage_backend: "minio",
    },
  ],
};

export const DEMO_EVENTS: Record<string, Event[]> = {
  [DEMO_RUN_IDS.failed]: [
    {
      event_id: "ev-1",
      run_id: DEMO_RUN_IDS.failed,
      event_type: "faultline.run.failed",
      level: "error",
      message: "Slurm node eviction (demo)",
      timestamp_ms: now - 120_000,
    },
    {
      event_id: "ev-2",
      run_id: DEMO_RUN_IDS.failed,
      event_type: "faultline.checkpoint.saved",
      level: "info",
      message: "checkpoint step 400",
      timestamp_ms: now - 180_000,
    },
    {
      event_id: "ev-4",
      run_id: DEMO_RUN_IDS.failed,
      event_type: "faultline.run.resume_completed",
      level: "info",
      message: "recovery succeeded from checkpoint step 400",
      timestamp_ms: now - 60_000,
    },
  ],
  [DEMO_RUN_IDS.completed]: [
    {
      event_id: "ev-3",
      run_id: DEMO_RUN_IDS.completed,
      event_type: "faultline.run.completed",
      level: "info",
      message: "training completed",
      timestamp_ms: now - 3_600_000,
    },
  ],
};

export const DEMO_RECOVERY: Record<string, RecoverySummary> = {
  [DEMO_RUN_IDS.failed]: {
    run_id: DEMO_RUN_IDS.failed,
    project_name: "faultline-demo",
    run_name: "slurm-protein-exp7",
    status: "failed",
    latest_step: 400,
    latest_checkpoint_step: 400,
    estimated_lost_steps: 12,
    has_checkpoint: true,
    checkpoint_health: "ok",
    restore_status: "ready",
    recovery_badge: "recoverable",
    recommendation: "resume_from_checkpoint",
    resume_snippet: "faultline.auto_resume(...)",
    inline_restore_snippet: "run.restore_latest(model=model)",
    slurm_snippet: "sbatch train.slurm",
    is_stale: false,
    display_status: "recoverable",
    can_resume: true,
  },
};

export function getDemoRun(id: string): Run | undefined {
  return DEMO_RUNS.find((r) => r.run_id === id);
}
