import type { Run } from "@/lib/types";

const INTEGRATION_LABELS: Record<string, string> = {
  "integration:huggingface": "HuggingFace",
  "integration:lightning": "Lightning",
  "integration:pytorch": "PyTorch",
  quickstart: "Quickstart",
};

export function integrationLabel(tags: string[] | undefined): string {
  if (!tags?.length) return "Raw SDK";
  for (const tag of tags) {
    if (tag in INTEGRATION_LABELS) return INTEGRATION_LABELS[tag];
    if (tag.startsWith("integration:")) {
      return tag.split(":", 2)[1] ?? "SDK";
    }
  }
  if (tags.includes("quickstart") || tags.includes("sdk-v20")) return "Quickstart";
  return "Raw SDK";
}

export function IntegrationBadge({ run }: { run: Run }) {
  const label = integrationLabel(run.tags);
  return (
    <span className="inline-flex items-center rounded-md border border-border bg-surface px-2 py-0.5 text-xs text-muted">
      {label}
    </span>
  );
}
