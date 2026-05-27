"use client";

import { CodeBlock } from "@/components/CodeBlock";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { resumeRun } from "@/lib/api";
import {
  formatAge,
  formatTimestamp,
  formatValue,
  recommendationText,
} from "@/lib/format";
import type { RecoverySummary } from "@/lib/types";
import { Play, RefreshCw } from "lucide-react";
import { useState } from "react";

function formatLaunchConfig(recovery: RecoverySummary): string {
  const cfg = recovery.launch_config;
  if (!cfg) {
    return "Not registered — call run.register_launch_command() or register_slurm_script()";
  }
  if (cfg.launch_type === "local_command") {
    return `Type: local_command\nCommand: ${JSON.stringify(cfg.command)}\nWorking dir: ${cfg.working_dir ?? "(default)"}`;
  }
  return `Type: slurm_script\nScript: ${cfg.script_path}\nWorking dir: ${cfg.working_dir ?? "(default)"}`;
}

export function RecoveryPanel({
  recovery,
  onResumed,
}: {
  recovery: RecoverySummary;
  onResumed?: () => void;
}) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<string | null>(null);

  async function handleResume() {
    setLoading(true);
    setError(null);
    try {
      const result = await resumeRun(recovery.run_id);
      setLastResult(
        `Started — pid ${result.pid ?? "—"}, slurm ${result.slurm_job_id ?? "—"}`
      );
      onResumed?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Resume failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <CardTitle>Crash-to-resume</CardTitle>
          <CardDescription>
            {recommendationText(recovery.recommendation)}
          </CardDescription>
        </div>
        <StatusBadge status={recovery.recovery_badge} />
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {[
          ["Latest metric step", recovery.latest_step],
          ["Latest checkpoint", recovery.has_checkpoint ? recovery.latest_checkpoint_step : "none"],
          ["Lost steps", recovery.estimated_lost_steps],
          ["Checkpoint health", recovery.checkpoint_health],
          ["Checkpoint age", formatAge(recovery.checkpoint_age_ms)],
          ["Restore status", recovery.restore_status],
        ].map(([label, value]) => (
          <div
            key={String(label)}
            className="rounded-lg bg-surface-2 px-3 py-2"
          >
            <p className="text-xs text-muted">{label}</p>
            <p className="font-semibold tabular-nums">{formatValue(value)}</p>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Button
          type="button"
          disabled={!recovery.can_resume || loading}
          onClick={handleResume}
        >
          {loading ? (
            <RefreshCw className="h-4 w-4 animate-spin" />
          ) : (
            <Play className="h-4 w-4" />
          )}
          Resume Run
        </Button>
        <p className="text-xs text-muted">
          Manual relaunch only — uses stored launch config, no auto-retry loop.
        </p>
      </div>
      {error ? <p className="text-sm text-danger">{error}</p> : null}
      {lastResult ? <p className="text-sm text-ok">{lastResult}</p> : null}

      {recovery.last_resume ? (
        <div className="text-sm text-muted border-t border-border pt-3">
          <p className="font-medium text-foreground mb-1">Last resume launch</p>
          <p>Status: {recovery.last_resume.status}</p>
          <p>At: {formatTimestamp(recovery.last_resume.launched_at_ms)}</p>
          {recovery.last_resume.pid != null && <p>PID: {recovery.last_resume.pid}</p>}
          {recovery.last_resume.slurm_job_id && (
            <p>Slurm job: {recovery.last_resume.slurm_job_id}</p>
          )}
        </div>
      ) : null}

      <div>
        <p className="text-sm font-medium mb-2">Launch configuration</p>
        <pre className="text-xs rounded-lg bg-surface-2 border border-border p-3 overflow-x-auto whitespace-pre-wrap">
          {formatLaunchConfig(recovery)}
        </pre>
      </div>

      <div>
        <p className="text-sm font-medium mb-2">Resume code</p>
        <CodeBlock code={recovery.resume_snippet} />
      </div>
      <div>
        <p className="text-sm font-medium mb-2">Slurm template</p>
        <CodeBlock code={recovery.slurm_snippet} />
      </div>
    </Card>
  );
}
