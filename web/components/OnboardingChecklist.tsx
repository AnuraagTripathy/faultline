"use client";

import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import type { ApiKeyListItem, Run } from "@/lib/types";
import { ONBOARDING_SNIPPET_COPIED_STORAGE } from "@/lib/starter-script";
import { CheckCircle2, Circle } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

export function OnboardingChecklist({
  apiOk,
  runs,
  apiKeys,
  usage,
}: {
  apiOk: boolean;
  runs: Run[];
  apiKeys: ApiKeyListItem[];
  usage: import("@/lib/types").Usage | null;
}) {
  const [snippetCopied, setSnippetCopied] = useState(false);

  useEffect(() => {
    const refresh = () => {
      setSnippetCopied(
        localStorage.getItem(ONBOARDING_SNIPPET_COPIED_STORAGE) === "1"
      );
    };
    refresh();
    window.addEventListener("storage", refresh);
    window.addEventListener("focus", refresh);
    return () => {
      window.removeEventListener("storage", refresh);
      window.removeEventListener("focus", refresh);
    };
  }, []);

  const hasRuns =
    runs.length > 0 ||
    (((usage?.runs_created ?? 0) > 0 || (usage?.metric_points_ingested ?? 0) > 0));
  const firstRunId = runs[0]?.run_id;
  const hasCreatedKey = apiKeys.length > 0;

  const steps = [
    {
      label: "Create an API key",
      detail: "Account → label your key (e.g. my-laptop)",
      done: hasCreatedKey,
      href: "/account",
    },
    {
      label: "Copy quickstart snippet",
      detail: "Quickstart → paste key → copy script with base_url",
      done: snippetCopied,
      href: "/quickstart",
    },
    {
      label: "Run first training script",
      detail: "python sdk/examples/cloud_pytorch_easy.py (or your snippet)",
      done: hasRuns && apiOk,
      href: "/quickstart",
    },
    {
      label: "View your first run",
      detail: "Open Runs and inspect metrics & checkpoints",
      done: hasRuns,
      href: firstRunId ? `/runs/${firstRunId}` : "/runs",
    },
  ];

  const completed = steps.filter((s) => s.done).length;

  return (
    <Card className="mb-6">
      <CardTitle>Getting started checklist</CardTitle>
      <CardDescription>
        {completed} of {steps.length} complete — connect a training script in
        minutes
      </CardDescription>
      <ul className="mt-4 space-y-3">
        {steps.map((step) => (
          <li key={step.label} className="flex gap-3 items-start">
            {step.done ? (
              <CheckCircle2 className="h-5 w-5 text-ok shrink-0 mt-0.5" />
            ) : (
              <Circle className="h-5 w-5 text-muted shrink-0 mt-0.5" />
            )}
            <div className="min-w-0">
              <Link
                href={step.href}
                className="font-medium text-foreground no-underline hover:underline"
              >
                {step.label}
              </Link>
              <p className="text-xs text-muted mt-0.5">{step.detail}</p>
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}
