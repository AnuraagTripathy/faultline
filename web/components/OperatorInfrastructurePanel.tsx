"use client";

import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { StatusBadge } from "@/components/StatusBadge";
import type { BackgroundTask, InfrastructureStatus } from "@/lib/types";
import { formatTimestamp } from "@/lib/format";

function StatusDot({ ok }: { ok: boolean }) {
  return (
    <span
      className={`inline-block h-2 w-2 rounded-full ${ok ? "bg-ok" : "bg-danger"}`}
    />
  );
}

export function OperatorInfrastructurePanel({
  infra,
  tasks,
}: {
  infra: InfrastructureStatus | null;
  tasks: BackgroundTask[];
}) {
  if (!infra) return null;

  const dbOk = infra.database.status === "ok";
  const storageOk = infra.object_storage.status === "ok";
  const workerOk = infra.background_worker.status === "ok";

  return (
    <div className="space-y-6">
      <Card>
        <CardTitle>Infrastructure</CardTitle>
        <CardDescription className="mt-1">
          Operator view — Faultline Cloud v{infra.version} (database, object storage, worker)
        </CardDescription>
        <ul className="mt-4 space-y-3 text-sm">
          <li className="flex items-center justify-between gap-4 rounded-lg bg-surface-2 px-3 py-2">
            <span className="flex items-center gap-2">
              <StatusDot ok={dbOk} />
              PostgreSQL / {infra.database.kind}
            </span>
            <StatusBadge status={dbOk ? "completed" : "failed"} />
          </li>
          <li className="flex items-center justify-between gap-4 rounded-lg bg-surface-2 px-3 py-2">
            <span className="flex items-center gap-2">
              <StatusDot ok={storageOk} />
              Object storage ({infra.object_storage.backend})
            </span>
            <StatusBadge status={storageOk ? "completed" : "failed"} />
          </li>
          <li className="flex items-center justify-between gap-4 rounded-lg bg-surface-2 px-3 py-2">
            <span className="flex items-center gap-2">
              <StatusDot ok={workerOk} />
              Background worker
              {infra.background_worker.queue_size != null ? (
                <span className="text-muted text-xs">
                  (queue {infra.background_worker.queue_size})
                </span>
              ) : null}
            </span>
            <StatusBadge status={workerOk ? "running" : "failed"} />
          </li>
        </ul>
      </Card>

      {tasks.length > 0 ? (
        <Card>
          <CardTitle>Recent background tasks</CardTitle>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-muted">
                <tr>
                  <th className="text-left py-1">Type</th>
                  <th className="text-left py-1">Status</th>
                  <th className="text-left py-1">Updated</th>
                </tr>
              </thead>
              <tbody>
                {tasks.slice(0, 8).map((t) => (
                  <tr key={t.task_id} className="border-t border-border">
                    <td className="py-1.5 font-mono">{t.task_type}</td>
                    <td className="py-1.5">
                      <StatusBadge status={t.status} />
                    </td>
                    <td className="py-1.5 text-muted">
                      {formatTimestamp(t.updated_at_ms)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ) : null}
    </div>
  );
}
