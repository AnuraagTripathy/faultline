import { cn } from "@/lib/cn";

const styles: Record<string, string> = {
  running: "bg-surface-2 text-foreground",
  completed: "bg-ok/15 text-ok",
  failed: "bg-danger/15 text-danger",
  stopped: "bg-warn/15 text-warn",
  recoverable: "bg-ok/15 text-ok",
  stale: "bg-warn/15 text-warn",
  resuming: "bg-surface-2 text-foreground",
  "no-checkpoint": "bg-muted/20 text-muted",
  "no_checkpoint": "bg-muted/20 text-muted",
  "checkpoint-missing": "bg-danger/15 text-danger",
  checkpoint_missing: "bg-danger/15 text-danger",
};

export function StatusBadge({
  status,
  className,
}: {
  status: string;
  className?: string;
}) {
  const key = status.toLowerCase().replace(/_/g, "-");
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold lowercase",
        styles[key] ?? styles[status.toLowerCase()] ?? "bg-surface-2 text-muted",
        className
      )}
    >
      {status.replace(/_/g, " ")}
    </span>
  );
}
