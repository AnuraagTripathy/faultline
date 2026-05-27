"use client";

import { Button } from "@/components/ui/button";
import { Copy } from "lucide-react";
import { useState } from "react";

export function resumeCliCommand(runId: string): string {
  return `python -m faultline.cli resume ${runId}`;
}

export function resumeSdkSnippet(runId: string): string {
  return `import faultline\nrun = faultline.attach(${JSON.stringify(runId)})\nstart_step = run.restore_latest(model=model, optimizer=optimizer)`;
}

export function ResumeCommandCopy({ runId }: { runId: string }) {
  const [copied, setCopied] = useState(false);
  const command = resumeCliCommand(runId);

  async function copy() {
    await navigator.clipboard.writeText(command);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-surface px-3 py-2 text-sm font-mono">
      <code className="text-accent flex-1 min-w-0 truncate">{command}</code>
      <Button variant="secondary" size="sm" onClick={() => void copy()}>
        <Copy className="h-3.5 w-3.5 mr-1" />
        {copied ? "Copied" : "Copy"}
      </Button>
    </div>
  );
}
