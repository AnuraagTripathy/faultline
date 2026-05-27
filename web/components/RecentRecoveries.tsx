"use client";

import { StatusBadge } from "@/components/StatusBadge";
import { Card, CardTitle } from "@/components/ui/card";
import type { RecoverySummary } from "@/lib/types";
import Link from "next/link";

export function RecentRecoveries({
  items,
}: {
  items: { run_id: string; run_name: string; recovery: RecoverySummary }[];
}) {
  if (items.length === 0) {
    return (
      <Card>
        <CardTitle>Recent recoveries</CardTitle>
        <p className="text-sm text-muted mt-3">No recoverable runs right now.</p>
      </Card>
    );
  }

  return (
    <Card>
      <CardTitle>Recent recoveries</CardTitle>
      <ul className="mt-4 space-y-3">
        {items.map(({ run_id, run_name, recovery }) => (
          <li key={run_id}>
            <Link
              href={`/runs/${run_id}`}
              className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border px-3 py-2 hover:border-accent/40 transition no-underline"
            >
              <span className="font-medium text-foreground">{run_name}</span>
              <StatusBadge status={recovery.display_status} />
            </Link>
            <p className="text-xs text-muted mt-1 pl-3">
              Lost ~{recovery.estimated_lost_steps} steps · checkpoint {recovery.latest_checkpoint_step}
            </p>
          </li>
        ))}
      </ul>
    </Card>
  );
}
