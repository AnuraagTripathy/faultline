import type { RecoverySummary } from "@/lib/types";

const BADGE_STYLES: Record<string, string> = {
  recoverable: "border-ok/30 bg-ok-soft text-ok",
  verified: "border-ok/30 bg-ok-soft text-ok",
  stale: "border-warn/30 bg-warn-soft text-warn",
  missing: "border-danger/30 bg-danger-soft text-danger",
  "missing checkpoint": "border-danger/30 bg-danger-soft text-danger",
};

function normalizeBadge(recovery: RecoverySummary): string {
  const badge = (recovery.recovery_badge || recovery.checkpoint_health || "").toLowerCase();
  if (!recovery.has_checkpoint) return "missing checkpoint";
  if (recovery.is_stale) return "stale";
  if (badge.includes("recover")) return "recoverable";
  if (badge.includes("verified") || recovery.checkpoint_health === "ok") return "verified";
  return badge || recovery.restore_status || "unknown";
}

export function RecoveryReadinessBadge({ recovery }: { recovery: RecoverySummary }) {
  const key = normalizeBadge(recovery);
  const style =
    BADGE_STYLES[key] ?? "border-border bg-surface-2 text-muted";
  const label = key.replace(/_/g, " ");

  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium capitalize ${style}`}>
      {label}
    </span>
  );
}
