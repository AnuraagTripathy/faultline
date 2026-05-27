"use client";

import { CodeBlock } from "@/components/CodeBlock";
import { DemoModeBadge } from "@/components/DemoModeBadge";
import { MetricChart } from "@/components/MetricChart";
import { StatusBadge } from "@/components/StatusBadge";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/cn";
import {
  DEMO_CHECKPOINTS,
  DEMO_EVENTS,
  DEMO_METRICS,
  DEMO_RECOVERY,
  DEMO_RUN_IDS,
  DEMO_RUNS,
} from "@/lib/demo-data";
import { formatBytes } from "@/lib/format";
import Link from "next/link";
import { useEffect, useState } from "react";

const PHASES = [
  {
    id: "train",
    label: "1. Training",
    short: "Training",
    headline: "Metrics stream while the job runs",
    body: "Your trainer reports loss and step to Faultline in real time. You can watch progress without SSHing into the node.",
  },
  {
    id: "checkpoint",
    label: "2. Checkpoint",
    short: "Checkpoint",
    headline: "State is saved to durable storage",
    body: "Each checkpoint is committed to object storage (MinIO/S3 in production). Metadata lives in Postgres so recovery stays auditable.",
  },
  {
    id: "crash",
    label: "3. Crash",
    short: "Crash",
    headline: "The job fails — but progress is not gone",
    body: "Spot preemption, Slurm eviction, or OOM marks the run failed. Faultline records the failure event and keeps your last good checkpoint.",
  },
  {
    id: "recover",
    label: "4. Recover",
    short: "Recover",
    headline: "Resume from the last checkpoint",
    body: "The dashboard estimates lost steps and gives you a copy-paste resume command — no digging through cluster logs.",
  },
] as const;

export function DemoWalkthrough() {
  const [phase, setPhase] = useState(0);
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    if (paused) return;
    const id = setInterval(() => {
      setPhase((p) => (p + 1) % PHASES.length);
    }, 5000);
    return () => clearInterval(id);
  }, [paused]);

  const current = PHASES[phase];

  const run =
    phase < 2
      ? DEMO_RUNS[0]
      : phase === 2
        ? { ...DEMO_RUNS[1], status: "failed" as const }
        : DEMO_RUNS[1];

  const metrics =
    phase < 2
      ? DEMO_METRICS[DEMO_RUN_IDS.running].slice(0, 30)
      : DEMO_METRICS[DEMO_RUN_IDS.failed];

  const checkpoints =
    phase >= 1 ? DEMO_CHECKPOINTS[DEMO_RUN_IDS.failed] : DEMO_CHECKPOINTS[DEMO_RUN_IDS.running];

  const events = phase >= 2 ? DEMO_EVENTS[DEMO_RUN_IDS.failed] ?? [] : [];
  const recovery = phase >= 3 ? DEMO_RECOVERY[DEMO_RUN_IDS.failed] : null;

  const resumeCmd = recovery
    ? `python -m faultline.cli resume ${recovery.run_id}`
    : null;

  return (
    <div className="space-y-8">
      <div className="rounded-xl border border-accent-muted/60 bg-accent-soft/30 px-4 py-3 sm:px-5 sm:py-4 flex flex-wrap items-center justify-between gap-3">
        <DemoModeBadge className="!text-sm" />
        <button
          type="button"
          onClick={() => setPaused((p) => !p)}
          className="text-xs text-muted hover:text-foreground font-medium"
        >
          {paused ? "Resume auto-play" : "Pause auto-play"}
        </button>
      </div>

      {/* Stepper */}
      <nav aria-label="Demo phases">
        <ol className="grid grid-cols-2 gap-2 sm:grid-cols-4 sm:gap-0">
          {PHASES.map((p, i) => {
            const active = i === phase;
            const done = i < phase;
            return (
              <li key={p.id} className="sm:flex-1">
                <button
                  type="button"
                  onClick={() => setPhase(i)}
                  className={cn(
                    "w-full text-left rounded-lg border px-3 py-3 transition-colors sm:rounded-none sm:border-0 sm:border-b-2 sm:px-4 sm:pb-3 sm:pt-0",
                    active
                      ? "border-accent bg-surface-elevated sm:border-accent text-foreground shadow-sm sm:shadow-none"
                      : done
                        ? "border-border bg-surface-elevated/50 sm:border-accent/40 text-foreground"
                        : "border-border bg-surface-elevated/30 sm:border-transparent text-muted hover:text-foreground hover:border-border"
                  )}
                >
                  <span className="block text-xs font-semibold uppercase tracking-wide text-accent mb-0.5 sm:mb-1">
                    Step {i + 1}
                  </span>
                  <span className="block text-sm font-medium">{p.short}</span>
                </button>
              </li>
            );
          })}
        </ol>
      </nav>

      {/* Context + run summary */}
      <div className="grid gap-6 lg:grid-cols-[1fr_minmax(0,18rem)]">
        <Card className="border-accent-muted/40">
          <p className="section-label mb-2">What you&apos;re seeing</p>
          <CardTitle className="text-lg mb-2">{current.headline}</CardTitle>
          <CardDescription className="text-[15px]">{current.body}</CardDescription>
        </Card>

        <Card>
          <p className="text-xs font-medium uppercase tracking-wide text-subtle mb-3">
            Simulated run
          </p>
          <div className="space-y-2">
            <StatusBadge status={run.status} />
            <p className="font-semibold text-foreground leading-snug">{run.run_name}</p>
            <p className="text-sm text-muted">{run.project_name}</p>
            <dl className="mt-4 space-y-2 text-sm border-t border-border pt-3">
              <div className="flex justify-between gap-2">
                <dt className="text-subtle">Latest step</dt>
                <dd className="font-mono text-foreground">{run.latest_step}</dd>
              </div>
              <div className="flex justify-between gap-2">
                <dt className="text-subtle">Checkpoint</dt>
                <dd className="font-mono text-foreground">
                  {run.latest_checkpoint_step ?? "—"}
                </dd>
              </div>
              {run.latest_loss != null ? (
                <div className="flex justify-between gap-2">
                  <dt className="text-subtle">Loss</dt>
                  <dd className="font-mono text-foreground">{run.latest_loss.toFixed(3)}</dd>
                </div>
              ) : null}
            </dl>
          </div>
        </Card>
      </div>

      {/* Metrics + checkpoints */}
      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardTitle className="text-sm font-medium text-muted mb-1">Live metrics</CardTitle>
          <CardDescription className="mb-4">
            Loss curve for this run — updates as training progresses in the real product.
          </CardDescription>
          <MetricChart points={metrics} />
        </Card>

        <Card>
          <CardTitle className="text-sm font-medium text-muted mb-1">Checkpoints</CardTitle>
          <CardDescription className="mb-4">
            Committed blobs you can restore from after a failure.
          </CardDescription>
          <ul className="space-y-3">
            {checkpoints.map((cp) => (
              <li
                key={cp.checkpoint_id}
                className="flex items-start justify-between gap-2 text-sm border-b border-border pb-3 last:border-0 last:pb-0"
              >
                <div>
                  <p className="font-medium text-foreground">Step {cp.step}</p>
                  <p className="text-xs text-subtle mt-0.5">{formatBytes(cp.size_bytes)}</p>
                </div>
                <span className="text-xs font-medium text-accent uppercase tracking-wide">
                  {cp.status}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      {/* Events */}
      {events.length > 0 ? (
        <Card>
          <CardTitle className="text-sm font-medium text-muted mb-3">Timeline</CardTitle>
          <ul className="space-y-3">
            {events.map((e) => (
              <li key={e.event_id} className="flex gap-3 text-sm">
                <span
                  className={cn(
                    "mt-1.5 h-2 w-2 shrink-0 rounded-full",
                    e.level === "error" ? "bg-red-500" : "bg-accent"
                  )}
                />
                <div>
                  <p className="text-foreground">{e.message}</p>
                  <p className="text-xs text-subtle mt-0.5">{e.event_type}</p>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      {/* Recovery */}
      {recovery ? (
        <Card className="border-accent/30 bg-accent-soft/20">
          <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
            <div>
              <CardTitle>Ready to resume</CardTitle>
              <CardDescription>
                ~{recovery.estimated_lost_steps} steps lost after step{" "}
                {recovery.latest_checkpoint_step}. Checkpoint health:{" "}
                {recovery.checkpoint_health}.
              </CardDescription>
            </div>
            <StatusBadge status={recovery.recovery_badge} />
          </div>
          {resumeCmd ? <CodeBlock code={resumeCmd} /> : null}
          <p className="text-xs text-subtle mt-3">
            In your cluster, run this from the same environment where training started.
          </p>
        </Card>
      ) : null}

      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pt-2 border-t border-border">
        <p className="text-sm text-muted max-w-md">
          Want the full dashboard with three sample runs? Browse the demo project or sign up to
          connect your own jobs.
        </p>
        <div className="flex flex-wrap gap-4 text-sm shrink-0">
          <Link href="/demo/runs" className="btn-ghost">
            All demo runs →
          </Link>
          <Link href="/signup" className="btn-primary !py-2 !px-4">
            Create free account
          </Link>
        </div>
      </div>
    </div>
  );
}
