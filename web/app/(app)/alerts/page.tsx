"use client";

import { AppShell } from "@/components/AppShell";
import { StatusBadge } from "@/components/StatusBadge";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { fetchRecovery, fetchRuns, ApiError } from "@/lib/api";
import type { RecoverySummary, Run } from "@/lib/types";
import Link from "next/link";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

type RunAlert = Run & { recovery?: RecoverySummary };

export default function AlertsPage() {
  const [items, setItems] = useState<RunAlert[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const runs = await fetchRuns();
      const interesting = runs.filter(
        (r) =>
          r.status === "failed" ||
          r.status === "stopped" ||
          r.status === "running"
      );
      const enriched = await Promise.all(
        interesting.slice(0, 20).map(async (run): Promise<RunAlert | null> => {
          try {
            const recovery = await fetchRecovery(run.run_id);
            if (
              recovery.is_stale ||
              recovery.recovery_badge === "recoverable" ||
              recovery.recovery_badge === "checkpoint_missing" ||
              run.status === "failed"
            ) {
              return { ...run, recovery };
            }
          } catch {
            if (run.status === "failed") return { ...run };
          }
          return null;
        })
      );
      setItems(enriched.filter((x): x is RunAlert => x !== null));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load alerts");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <AppShell
      title="Alerts"
      subtitle="Failed, stale, and recoverable runs (cloud alerts API coming soon)"
      actions={
        <Button variant="secondary" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      }
    >
      <Card className="mb-6 border-warn/30 bg-warn/5">
        <CardTitle className="flex items-center gap-2 text-warn">
          <AlertTriangle className="h-5 w-5" />
          Lightweight alert view
        </CardTitle>
        <CardDescription>
          Full cloud alerting (thresholds, notifications) is not built yet. This page
          derives attention items from run status and the recovery endpoint.
        </CardDescription>
      </Card>

      {error ? <p className="text-danger text-sm mb-4">{error}</p> : null}

      {!items.length && !loading ? (
        <p className="text-muted text-sm">No failed or recoverable runs right now.</p>
      ) : (
        <ul className="space-y-3">
          {items.map((item) => (
            <li key={item.run_id}>
              <Card className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <Link
                    href={`/runs/${item.run_id}`}
                    className="font-medium text-accent no-underline hover:underline"
                  >
                    {item.run_name}
                  </Link>
                  <p className="text-sm text-muted">{item.project_name}</p>
                  <div className="flex gap-2 mt-2">
                    <StatusBadge status={item.recovery?.display_status ?? item.status} />
                    {item.recovery ? (
                      <StatusBadge status={item.recovery.recovery_badge} />
                    ) : null}
                  </div>
                </div>
                <div className="text-sm text-muted text-right">
                  {item.recovery ? (
                    <>
                      <p>Lost steps: {item.recovery.estimated_lost_steps}</p>
                      <p>Health: {item.recovery.checkpoint_health}</p>
                    </>
                  ) : (
                    <p>Status: {item.status}</p>
                  )}
                </div>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </AppShell>
  );
}
