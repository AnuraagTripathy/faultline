import type { RecoverySummary } from "@/lib/types";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";

export function RecoveryEmptyHint({
  recovery,
}: {
  recovery: RecoverySummary;
}) {
  if (recovery.has_checkpoint && recovery.recommendation !== "run_completed") {
    return null;
  }

  let message =
    "Recovery details appear when a run has logged metrics and optionally failed mid-training.";
  if (recovery.recommendation === "run_completed") {
    message =
      "This run completed successfully. Recovery is for failed or interrupted jobs with checkpoints.";
  } else if (!recovery.has_checkpoint) {
    message =
      "Upload a checkpoint with run.save() during training. After a failure, you will see lost steps, resume snippets, and a Resume Run button here.";
  }

  return (
    <Card className="mb-6 border-dashed border-border bg-surface-2/30">
      <CardTitle className="text-base">When recovery appears</CardTitle>
      <CardDescription className="mt-2">{message}</CardDescription>
    </Card>
  );
}
