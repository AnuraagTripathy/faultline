"use client";

import { AppShell } from "@/components/AppShell";
import { OperatorInfrastructurePanel } from "@/components/OperatorInfrastructurePanel";
import { fetchInfrastructure, fetchTasks, ApiError } from "@/lib/api";
import type { BackgroundTask, InfrastructureStatus } from "@/lib/types";
import { useCallback, useEffect, useState } from "react";

export default function AdminInfrastructurePage() {
  const [infra, setInfra] = useState<InfrastructureStatus | null>(null);
  const [tasks, setTasks] = useState<BackgroundTask[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [infraData, taskList] = await Promise.all([
        fetchInfrastructure(),
        fetchTasks(),
      ]);
      setInfra(infraData);
      setTasks(taskList);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load infrastructure");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <AppShell
      title="Infrastructure"
      subtitle="Operator preview — backend health for this Faultline Cloud deployment"
    >
      <p className="text-sm text-muted mb-6 rounded-lg border border-border bg-surface-2 px-4 py-3">
        This page is for operators and self-hosters. Normal users manage API keys and alerts on{" "}
        <strong className="text-foreground">Account</strong>.
      </p>
      {error ? <p className="text-danger text-sm mb-4">{error}</p> : null}
      <OperatorInfrastructurePanel infra={infra} tasks={tasks} />
    </AppShell>
  );
}
