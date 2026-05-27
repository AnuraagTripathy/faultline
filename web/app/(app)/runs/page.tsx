"use client";

import { AppShell } from "@/components/AppShell";
import { LiveIndicator } from "@/components/LiveIndicator";
import { RunsEmptyState } from "@/components/RunsEmptyState";
import { StatusBadge } from "@/components/StatusBadge";
import { IntegrationBadge } from "@/components/IntegrationBadge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { fetchRuns, ApiError } from "@/lib/api";
import { formatLoss, formatTimestamp } from "@/lib/format";
import type { Run } from "@/lib/types";
import { hasRunningRun, useLivePoll } from "@/lib/use-live-poll";
import { RefreshCw } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

export default function RunsPage() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (opts?: { silent?: boolean }) => {
    if (!opts?.silent) {
      setLoading(true);
      setError(null);
    }
    try {
      setRuns(await fetchRuns());
    } catch (e) {
      if (!opts?.silent) {
        setError(e instanceof ApiError ? e.message : "Failed to load runs");
      }
    } finally {
      if (!opts?.silent) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useLivePoll(() => load({ silent: true }), hasRunningRun(runs));

  return (
    <AppShell
      title="Runs"
      subtitle="All training jobs"
      actions={
        <>
          <LiveIndicator active={hasRunningRun(runs)} />
          <Button variant="secondary" size="sm" onClick={() => void load()} disabled={loading}>
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          </Button>
        </>
      }
    >
      {error ? <p className="text-danger text-sm mb-4">{error}</p> : null}
      {runs.length === 0 && !loading ? (
        <RunsEmptyState />
      ) : (
        <div className="space-y-3">
          {runs.map((run) => (
            <Link key={run.run_id} href={`/runs/${run.run_id}`} className="block no-underline">
              <Card className="hover:border-accent/30 transition-all duration-200">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <p className="font-semibold text-foreground">{run.run_name}</p>
                    <p className="text-sm text-muted">{run.project_name}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <IntegrationBadge run={run} />
                    <StatusBadge status={run.status} />
                  </div>
                </div>
                <p className="text-xs text-muted mt-2">
                  Step {run.latest_step} · loss {formatLoss(run.latest_loss)} ·{" "}
                  {formatTimestamp(run.updated_at_ms)}
                </p>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </AppShell>
  );
}
