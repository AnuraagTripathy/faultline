export function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  return String(value);
}

export function formatLoss(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value.toFixed(4);
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

export function formatTimestamp(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  const date = new Date(ms);
  if (Number.isNaN(date.getTime())) return String(ms);
  return date.toLocaleString();
}

export function formatAge(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(0)}s ago`;
  if (seconds < 3600) return `${(seconds / 60).toFixed(1)}m ago`;
  return `${(seconds / 3600).toFixed(1)}h ago`;
}

export function recommendationText(recommendation: string): string {
  const map: Record<string, string> = {
    resume_from_checkpoint:
      "This run can resume from the latest checkpoint. Copy the snippet or click Resume Run.",
    no_checkpoint:
      "No checkpoint found. Re-start training or upload a checkpoint before the next crash.",
    run_completed: "Run completed successfully. No resume needed.",
  };
  return map[recommendation] ?? recommendation;
}
