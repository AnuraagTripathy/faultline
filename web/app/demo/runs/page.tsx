"use client";

import { DemoModeBadge } from "@/components/DemoModeBadge";
import { StatusBadge } from "@/components/StatusBadge";
import { Card } from "@/components/ui/card";
import { DEMO_RUNS } from "@/lib/demo-data";
import { formatTimestamp } from "@/lib/format";
import Link from "next/link";

export default function DemoRunsPage() {
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Demo runs</h1>
          <p className="text-sm text-muted">Sample training jobs — explore without an account</p>
        </div>
        <DemoModeBadge />
      </div>
      <div className="space-y-3">
        {DEMO_RUNS.map((run) => (
          <Link key={run.run_id} href={`/demo/runs/${run.run_id}`} className="block no-underline">
            <Card className="hover:border-accent/40 transition-colors">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <p className="font-semibold text-foreground">{run.run_name}</p>
                  <p className="text-sm text-muted">{run.project_name}</p>
                </div>
                <StatusBadge status={run.status} />
              </div>
              <p className="text-xs text-muted mt-2">
                Step {run.latest_step} · updated {formatTimestamp(run.updated_at_ms)}
              </p>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}
