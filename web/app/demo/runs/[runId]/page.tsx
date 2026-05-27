"use client";

import { CheckpointTimeline } from "@/components/CheckpointTimeline";
import { DemoModeBadge } from "@/components/DemoModeBadge";
import { EventsTimeline } from "@/components/EventsTimeline";
import { IntegrationBadge } from "@/components/IntegrationBadge";
import { MetricChart } from "@/components/MetricChart";
import { RecoveryReadinessBadge } from "@/components/RecoveryReadinessBadge";
import { StatusBadge } from "@/components/StatusBadge";
import { Card, CardTitle } from "@/components/ui/card";
import {
  DEMO_CHECKPOINTS,
  DEMO_EVENTS,
  DEMO_METRICS,
  DEMO_RECOVERY,
  getDemoRun,
} from "@/lib/demo-data";
import { formatLoss, formatTimestamp } from "@/lib/format";
import { useParams } from "next/navigation";

export default function DemoRunDetailPage() {
  const params = useParams();
  const runId = params.runId as string;
  const run = getDemoRun(runId);
  const metrics = DEMO_METRICS[runId] ?? [];
  const checkpoints = DEMO_CHECKPOINTS[runId] ?? [];
  const events = DEMO_EVENTS[runId] ?? [];
  const recovery = DEMO_RECOVERY[runId] ?? null;

  if (!run) {
    return <p className="text-muted">Demo run not found.</p>;
  }

  return (
    <div className="space-y-6">
      <DemoModeBadge />
      <div className="flex flex-wrap items-center gap-3">
        <StatusBadge status={run.status} />
        <IntegrationBadge run={run} />
        {recovery ? <RecoveryReadinessBadge recovery={recovery} /> : null}
        <h1 className="text-2xl font-bold">{run.run_name}</h1>
      </div>
      <p className="text-sm text-muted">
        Step {run.latest_step} · loss {formatLoss(run.latest_loss)} ·{" "}
        {formatTimestamp(run.updated_at_ms)}
      </p>

      {recovery ? (
        <Card className="border-accent/30">
          <CardTitle>Recovery</CardTitle>
          <p className="text-sm text-muted mt-2">{recovery.recommendation}</p>
          <code className="block mt-2 text-xs text-accent">
            python -m faultline.cli resume {run.run_id}
          </code>
        </Card>
      ) : null}

      <Card>
        <CardTitle>Metrics</CardTitle>
        <div className="mt-4">
          <MetricChart points={metrics} />
        </div>
      </Card>

      <Card>
        <CardTitle>Checkpoints</CardTitle>
        <div className="mt-4">
          <CheckpointTimeline checkpoints={checkpoints} />
        </div>
      </Card>

      {events.length > 0 ? (
        <Card>
          <CardTitle>Events</CardTitle>
          <div className="mt-4">
            <EventsTimeline events={events} />
          </div>
        </Card>
      ) : null}
    </div>
  );
}
