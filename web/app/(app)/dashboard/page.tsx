"use client";

import { AppShell } from "@/components/AppShell";
import { LiveIndicator } from "@/components/LiveIndicator";
import { PlatformStatusBadge } from "@/components/PlatformStatusBadge";
import { OnboardingChecklist } from "@/components/OnboardingChecklist";
import { RecentRecoveries } from "@/components/RecentRecoveries";
import { StatCard } from "@/components/StatCard";
import { EventsTimeline } from "@/components/EventsTimeline";
import { Card, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  fetchApiKeys,
  fetchInfrastructure,
  fetchMe,
  fetchRecovery,
  fetchRuns,
  fetchEvents,
  fetchRecoveryStats,
  ApiError,
} from "@/lib/api";
import type { InfrastructureStatus, RecoverySummary } from "@/lib/types";
import { formatBytes, formatTimestamp } from "@/lib/format";
import type { ApiKeyListItem, Event, Run } from "@/lib/types";
import {
  Activity,
  AlertTriangle,
  Box,
  List,
  RefreshCw,
} from "lucide-react";
import { hasRunningRun, useLivePoll } from "@/lib/use-live-poll";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

export default function DashboardPage() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [apiKeys, setApiKeys] = useState<ApiKeyListItem[]>([]);
  const [usage, setUsage] = useState<import("@/lib/types").Usage | null>(null);
  const [userEmail, setUserEmail] = useState<string | null>(null);
  const [recoverable, setRecoverable] = useState(0);
  const [failed, setFailed] = useState(0);
  const [recentEvents, setRecentEvents] = useState<Event[]>([]);
  const [recentRecoveries, setRecentRecoveries] = useState<
    { run_id: string; run_name: string; recovery: RecoverySummary }[]
  >([]);
  const [infra, setInfra] = useState<InfrastructureStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [apiOk, setApiOk] = useState(false);
  const [recoveryStats, setRecoveryStats] = useState<import("@/lib/types").RecoveryStats | null>(null);

  const load = useCallback(async (opts?: { silent?: boolean }) => {
    if (!opts?.silent) {
      setLoading(true);
      setError(null);
    }
    try {
      const [me, runList, keyList, infraStatus] = await Promise.all([
        fetchMe(),
        fetchRuns(),
        fetchApiKeys(),
        fetchInfrastructure().catch(() => null),
      ]);
      setInfra(infraStatus);
      setApiOk(true);
      setUsage(me.usage);
      setUserEmail(me.user.email);
      setRuns(runList);
      setApiKeys(keyList);
      setRecoveryStats(await fetchRecoveryStats().catch(() => null));

      setFailed(runList.filter((r) => r.status === "failed").length);

      const candidates = runList.filter(
        (r) => r.status === "failed" || r.status === "stopped"
      );
      let recCount = 0;
      const recItems: { run_id: string; run_name: string; recovery: RecoverySummary }[] = [];
      await Promise.all(
        candidates.slice(0, 12).map(async (r) => {
          try {
            const rec = await fetchRecovery(r.run_id);
            if (rec.can_resume || rec.recovery_badge === "recoverable") {
              recCount++;
              recItems.push({ run_id: r.run_id, run_name: r.run_name, recovery: rec });
            }
          } catch {
            /* ignore */
          }
        })
      );
      setRecoverable(recCount);
      setRecentRecoveries(recItems.slice(0, 5));

      const latest = runList[0];
      if (latest) {
        const events = await fetchEvents(latest.run_id, 15);
        setRecentEvents(events);
      } else {
        setRecentEvents([]);
      }
    } catch (e) {
      if (!opts?.silent) {
        setApiOk(false);
        setError(e instanceof ApiError ? e.message : "Failed to load dashboard");
      }
    } finally {
      if (!opts?.silent) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const isLive = hasRunningRun(runs);
  useLivePoll(() => load({ silent: true }), isLive);

  const running = runs.filter((r) => r.status === "running").length;
  const latest = runs[0];

  return (
    <AppShell
      title="Overview"
      subtitle="Faultline Cloud at a glance"
      actions={
        <>
          <PlatformStatusBadge infra={infra} />
          <LiveIndicator active={isLive} />
          <Button
            variant="secondary"
            size="sm"
            onClick={() => void load()}
            disabled={loading}
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </>
      }
    >
      {error ? (
        <p className="text-danger mb-4 text-sm">{error}</p>
      ) : null}

      {userEmail && usage && usage.runs_created > 0 && runs.length === 0 ? (
        <div className="mb-4 border-l-2 border-border pl-4 text-sm text-muted">
          <p className="text-foreground font-medium mb-1">Usage shows activity, but the run list is empty</p>
          <p>
            Signed in as <strong className="text-foreground">{userEmail}</strong>. Try logging out and
            back in, then Refresh. If runs still do not appear, confirm your training script uses{" "}
            <code className="font-mono text-sm">base_url=&quot;http://127.0.0.1:8080&quot;</code> and an
            API key from this account (Account page).
          </p>
        </div>
      ) : null}

      <OnboardingChecklist
        apiOk={apiOk}
        runs={runs}
        apiKeys={apiKeys}
        usage={usage}
      />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4 mb-6">
        <StatCard label="Total runs" value={runs.length} icon={List} />
        <StatCard label="Running" value={running} icon={Activity} />
        <StatCard
          label="Failed / recoverable"
          value={`${failed} / ${recoverable}`}
          hint="Recoverable from recovery API"
          icon={AlertTriangle}
        />
        <StatCard
          label="Checkpoints"
          value={usage?.checkpoints_created ?? "—"}
          icon={Box}
        />
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 mb-6">
        <StatCard
          label="Avg lost steps"
          value={recoveryStats?.avg_lost_steps ?? "—"}
          hint="Failed/stopped runs"
        />
        <StatCard
          label="Successful resumes"
          value={recoveryStats?.successful_resumes ?? "—"}
        />
        <StatCard
          label="Time lost avoided"
          value={recoveryStats?.time_lost_avoided_steps ?? "—"}
          hint="Recovered checkpoint steps"
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <RecentRecoveries items={recentRecoveries} />
        <Card>
          <CardTitle>Usage</CardTitle>
          <ul className="mt-3 space-y-2 text-sm text-muted">
            <li>Runs created: <strong className="text-foreground">{usage?.runs_created ?? "—"}</strong></li>
            <li>Metric points: <strong className="text-foreground">{usage?.metric_points_ingested ?? "—"}</strong></li>
            <li>Checkpoints created: <strong className="text-foreground">{usage?.checkpoints_created ?? "—"}</strong></li>
            <li>Checkpoint bytes: <strong className="text-foreground">{formatBytes(usage?.checkpoint_bytes_uploaded)}</strong></li>
          </ul>
        </Card>

        <Card>
          <CardTitle>Latest run</CardTitle>
          {latest ? (
            <div className="mt-3 text-sm">
              <Link href={`/runs/${latest.run_id}`} className="text-accent font-medium text-lg">
                {latest.run_name}
              </Link>
              <p className="text-muted">{latest.project_name}</p>
              <p className="mt-2">Step {latest.latest_step} · checkpoint {latest.latest_checkpoint_step}</p>
              <p className="text-muted text-xs">{formatTimestamp(latest.updated_at_ms)}</p>
            </div>
          ) : (
            <p className="text-sm text-muted mt-3">No runs yet. Run a training demo script.</p>
          )}
        </Card>
      </div>

      <Card className="mt-6">
        <CardTitle>Recent events (latest run)</CardTitle>
        <div className="mt-4">
          <EventsTimeline events={recentEvents} />
        </div>
      </Card>
    </AppShell>
  );
}
