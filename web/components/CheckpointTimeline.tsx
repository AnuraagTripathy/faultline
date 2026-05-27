import { formatAge, formatTimestamp } from "@/lib/format";
import type { Checkpoint } from "@/lib/types";

export function CheckpointTimeline({ checkpoints }: { checkpoints: Checkpoint[] }) {
  if (checkpoints.length === 0) return null;

  const sorted = [...checkpoints].sort((a, b) => a.step - b.step);
  const latest = sorted[sorted.length - 1];
  const latestAge =
    latest.created_at_ms != null ? formatAge(Date.now() - latest.created_at_ms) : "—";

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-sm text-muted">
        <span>
          Latest checkpoint: step <strong className="text-foreground">{latest.step}</strong>
        </span>
        <span className="rounded-md border border-border bg-surface px-2 py-0.5 text-xs">
          {latestAge} ago
        </span>
        {latest.status ? (
          <span className="rounded-md border border-border px-2 py-0.5 text-xs capitalize">
            {latest.status}
          </span>
        ) : null}
      </div>
      <div className="flex items-end gap-1 overflow-x-auto pb-2">
        {sorted.map((cp) => {
          const height = 12 + Math.min(48, Math.max(8, Math.log10(cp.size_bytes + 1) * 8));
          return (
            <div
              key={cp.checkpoint_id}
              className="flex flex-col items-center min-w-[2.5rem]"
              title={`Step ${cp.step} · ${formatTimestamp(cp.created_at_ms ?? 0)}`}
            >
              <div
                className="w-2 rounded-t bg-foreground/70"
                style={{ height: `${height}px` }}
              />
              <span className="text-[10px] text-muted mt-1">{cp.step}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
