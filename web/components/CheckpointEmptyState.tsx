import { CodeBlock } from "@/components/CodeBlock";

const SAVE_SNIPPET = `if step % 100 == 0:
    run.save(model=model, optimizer=optimizer, step=step)`;

export function CheckpointEmptyState() {
  return (
    <div className="rounded-lg border border-dashed border-border bg-surface-2/50 p-6">
      <p className="text-sm text-muted mb-3">
        No checkpoints uploaded for this run yet. Call{" "}
        <code className="text-accent">run.save()</code> during training so you can
        resume after a crash.
      </p>
      <CodeBlock code={SAVE_SNIPPET} />
    </div>
  );
}
