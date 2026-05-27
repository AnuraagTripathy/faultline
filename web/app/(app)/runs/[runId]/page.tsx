"use client";

import { AppShell } from "@/components/AppShell";
import { CheckpointEmptyState } from "@/components/CheckpointEmptyState";
import { CheckpointTable } from "@/components/CheckpointTable";
import { CheckpointTimeline } from "@/components/CheckpointTimeline";
import { EventsTimeline } from "@/components/EventsTimeline";
import { IntegrationBadge } from "@/components/IntegrationBadge";
import { LiveIndicator } from "@/components/LiveIndicator";
import { MetricChart } from "@/components/MetricChart";
import { RecoveryEmptyHint } from "@/components/RecoveryEmptyHint";
import { RecoveryPanel } from "@/components/RecoveryPanel";
import { RecoveryReadinessBadge } from "@/components/RecoveryReadinessBadge";
import { ResumeCommandCopy } from "@/components/ResumeCommandCopy";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";
import {
  fetchCheckpoints,
  fetchEvents,
  fetchMetrics,
  fetchRecovery,
  fetchRun,
  ApiError,
} from "@/lib/api";
import { formatLoss, formatTimestamp } from "@/lib/format";
import type { Checkpoint, Event, MetricPoint, RecoverySummary, Run } from "@/lib/types";
import { useLivePoll } from "@/lib/use-live-poll";
import { RefreshCw } from "lucide-react";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

export default function RunDetailPage() {
  const params = useParams();
  const runId = params.runId as string;
  const [run, setRun] = useState<Run | null>(null);
  const [metrics, setMetrics] = useState<MetricPoint[]>([]);
  const [checkpoints, setCheckpoints] = useState<Checkpoint[]>([]);
  const [events, setEvents] = useState<Event[]>([]);
  const [recovery, setRecovery] = useState<RecoverySummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (opts?: { silent?: boolean }) => {
    if (!runId) return;
    if (!opts?.silent) {
      setLoading(true);
      setError(null);
    }
    try {
      const [r, m, c, e, rec] = await Promise.all([
        fetchRun(runId),
        fetchMetrics(runId),
        fetchCheckpoints(runId),
        fetchEvents(runId),
        fetchRecovery(runId),
      ]);
      setRun(r);
      setMetrics(m);
      setCheckpoints(c);
      setEvents(e);
      setRecovery(rec);
    } catch (err) {
      if (!opts?.silent) {
        setError(err instanceof ApiError ? err.message : "Failed to load run");
      }
    } finally {
      if (!opts?.silent) setLoading(false);
    }
  }, [runId]);

  useEffect(() => {
    void load();
  }, [load]);

  const isLive = run?.status === "running";
  useLivePoll(() => load({ silent: true }), isLive);

  const displayStatus = recovery?.display_status ?? run?.status ?? "unknown";

  return (
    <AppShell
      title={run?.run_name ?? "Run"}
      subtitle={run ? `${run.project_name}` : runId}
      actions={
        <>
          <LiveIndicator active={isLive} />
          <Button variant="secondary" size="sm" onClick={() => void load()} disabled={loading}>
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          </Button>
        </>
      }
    >
      {error ? <p className="text-danger text-sm mb-4">{error}</p> : null}
      {run ? (
        <div className="flex flex-wrap items-center gap-3 mb-6">
          <StatusBadge status={displayStatus} />
          <IntegrationBadge run={run} />
          {recovery ? <RecoveryReadinessBadge recovery={recovery} /> : null}
          <span className="text-sm text-muted">
            Step {run.latest_step} · loss {formatLoss(run.latest_loss)}
          </span>
        </div>
      ) : null}
      {run ? (
        <div className="mb-6">
          <ResumeCommandCopy runId={run.run_id} />
        </div>
      ) : null}
      {recovery ? (
        <div className="mb-6 space-y-4">
          <RecoveryEmptyHint recovery={recovery} />
          <RecoveryPanel recovery={recovery} onResumed={load} />
        </div>
      ) : null}
      <div className="grid gap-6">
        <Card className="transition-shadow hover:shadow-lg hover:shadow-black/20">
          <CardTitle>Metrics</CardTitle>
          <div className="mt-4">
            <MetricChart points={metrics} />
          </div>
        </Card>
        <Card>
          <CardTitle>Checkpoints</CardTitle>
          {checkpoints.length === 0 ? (
            <CheckpointEmptyState />
          ) : (
            <>
              <CheckpointTimeline checkpoints={checkpoints} />
              <div className="mt-6">
                <CheckpointTable runId={runId} checkpoints={checkpoints} />
              </div>
            </>
          )}
        </Card>
        <Card>
          <CardTitle>Events</CardTitle>
          <div className="mt-4">
            <EventsTimeline events={events} />
          </div>
        </Card>
      </div>
    </AppShell>
  );
}
