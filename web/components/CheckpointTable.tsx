"use client";

import { downloadCheckpoint } from "@/lib/api";
import { formatBytes, formatTimestamp } from "@/lib/format";
import type { Checkpoint } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/StatusBadge";
import { Download } from "lucide-react";
import { useState } from "react";

export function CheckpointTable({
  runId,
  checkpoints,
}: {
  runId: string;
  checkpoints: Checkpoint[];
}) {
  const [downloading, setDownloading] = useState<string | null>(null);

  if (!checkpoints.length) {
    return (
      <p className="text-sm text-muted">No checkpoints uploaded for this run.</p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-sm">
        <thead className="bg-surface-2 text-muted">
          <tr>
            <th className="px-3 py-2 text-left font-medium">Step</th>
            <th className="px-3 py-2 text-left font-medium">Size</th>
            <th className="px-3 py-2 text-left font-medium">Backend</th>
            <th className="px-3 py-2 text-left font-medium">Status</th>
            <th className="px-3 py-2 text-left font-medium">Created</th>
            <th className="px-3 py-2 text-right font-medium"></th>
          </tr>
        </thead>
        <tbody>
          {checkpoints.map((cp) => (
            <tr key={cp.checkpoint_id} className="border-t border-border">
              <td className="px-3 py-2 font-mono">{cp.step}</td>
              <td className="px-3 py-2">{formatBytes(cp.size_bytes)}</td>
              <td className="px-3 py-2">
                <StatusBadge status={cp.storage_backend ?? "local"} />
              </td>
              <td className="px-3 py-2">
                <StatusBadge status={cp.status} />
              </td>
              <td className="px-3 py-2 text-muted">
                {formatTimestamp(cp.created_at_ms ?? null)}
              </td>
              <td className="px-3 py-2 text-right">
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  disabled={downloading === cp.checkpoint_id}
                  onClick={async () => {
                    setDownloading(cp.checkpoint_id);
                    try {
                      await downloadCheckpoint(
                        runId,
                        cp.checkpoint_id,
                        `step_${cp.step}.pkl`
                      );
                    } finally {
                      setDownloading(null);
                    }
                  }}
                >
                  <Download className="h-3.5 w-3.5" />
                  Download
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
