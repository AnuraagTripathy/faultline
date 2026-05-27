"use client";

import { CodeBlock } from "@/components/CodeBlock";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/cn";
import { ONBOARDING_API_KEY_STORAGE } from "@/lib/starter-script";
import { useEffect, useMemo, useState } from "react";

const ENVIRONMENTS = [
  { id: "laptop", label: "Laptop" },
  { id: "hpc", label: "HPC / Slurm" },
  { id: "cloud", label: "Cloud GPU" },
] as const;

const FRAMEWORKS = [
  { id: "raw", label: "Raw PyTorch" },
  { id: "huggingface", label: "HuggingFace" },
  { id: "lightning", label: "Lightning" },
] as const;

type EnvId = (typeof ENVIRONMENTS)[number]["id"];
type FwId = (typeof FRAMEWORKS)[number]["id"];

function buildSnippet(env: EnvId, fw: FwId, apiKey: string): { install: string; script: string; recovery: string } {
  const base = 'base_url="http://127.0.0.1:8080"';
  const key = `api_key="${apiKey || "YOUR_API_KEY"}"`;

  const install =
    env === "hpc"
      ? "pip install faultline-sdk\nexport FAULTLINE_API_KEY=fl_...\nexport FAULTLINE_API_URL=https://api.your-org.com"
      : env === "cloud"
        ? "pip install faultline-sdk\nexport FAULTLINE_API_KEY=fl_...\nexport FAULTLINE_API_URL=https://api.your-org.com"
        : "pip install faultline-sdk\npython -m faultline.cli init";

  if (fw === "huggingface") {
    return {
      install,
      script: `from faultline.integrations import FaultlineTrainerCallback
from transformers import Trainer

callback = FaultlineTrainerCallback(
    project="my-project",
    run_name="finetune-1",
    ${key},
    ${base},
    auto_resume=True,
)
trainer = Trainer(..., callbacks=[callback])
trainer.train()`,
      recovery: "# After crash: re-run trainer — callback auto-resumes from latest checkpoint",
    };
  }
  if (fw === "lightning") {
    return {
      install,
      script: `import lightning as pl
from faultline.integrations import FaultlineLightningCallback

cb = FaultlineLightningCallback(
    project="my-project",
    run_name="exp-1",
    ${key},
    ${base},
    auto_resume=True,
)
trainer = pl.Trainer(callbacks=[cb])
trainer.fit(model, datamodule)`,
      recovery: "trainer.fit(model)  # FaultlineLightningCallback restores on train start",
    };
  }

  const resumeExtra =
    env === "hpc"
      ? '\nrun.register_slurm_script("train.slurm")  # optional relaunch'
      : "";

  return {
    install,
    script: `import faultline

run, start_step = faultline.auto_resume(
    project="my-project",
    run_name="exp-1",
    model=model,
    optimizer=optimizer,
    ${key},
    ${base},
)${resumeExtra}

for step in range(start_step, 1000):
    run.log(loss=loss, step=step)
    if step % 100 == 0:
        run.save(model=model, optimizer=optimizer, step=step)

run.complete()`,
    recovery: `# Or attach after crash:
run = faultline.attach("RUN_ID", ${key}, ${base})
start_step = run.restore_latest(model=model, optimizer=optimizer)`,
  };
}

export function QuickstartWizard({ apiKey: apiKeyProp = "" }: { apiKey?: string }) {
  const [env, setEnv] = useState<EnvId>("laptop");
  const [fw, setFw] = useState<FwId>("raw");
  const [storedKey, setStoredKey] = useState("");
  useEffect(() => {
    if (typeof window !== "undefined") {
      setStoredKey(localStorage.getItem(ONBOARDING_API_KEY_STORAGE) ?? "");
    }
  }, []);
  const apiKey = apiKeyProp || storedKey;
  const snippets = useMemo(() => buildSnippet(env, fw, apiKey), [env, fw, apiKey]);

  return (
    <Card>
      <CardTitle>Quickstart wizard</CardTitle>
      <CardDescription className="mb-4">
        Pick your environment and framework — we generate tailored commands.
      </CardDescription>
      <p className="text-xs text-muted mb-2">Environment</p>
      <div className="flex flex-wrap gap-2 mb-4">
        {ENVIRONMENTS.map((e) => (
          <button
            key={e.id}
            type="button"
            onClick={() => setEnv(e.id)}
            className={cn(
              "rounded-lg px-3 py-1.5 text-sm border transition",
              env === e.id
                ? "border-accent bg-accent/15 text-accent"
                : "border-border text-muted hover:text-foreground"
            )}
          >
            {e.label}
          </button>
        ))}
      </div>
      <p className="text-xs text-muted mb-2">Framework</p>
      <div className="flex flex-wrap gap-2 mb-6">
        {FRAMEWORKS.map((f) => (
          <button
            key={f.id}
            type="button"
            onClick={() => setFw(f.id)}
            className={cn(
              "rounded-lg px-3 py-1.5 text-sm border transition",
              fw === f.id
                ? "border-accent bg-accent/15 text-accent"
                : "border-border text-muted hover:text-foreground"
            )}
          >
            {f.label}
          </button>
        ))}
      </div>
      <p className="text-sm font-medium mb-2">Install</p>
      <CodeBlock code={snippets.install} />
      <p className="text-sm font-medium mb-2 mt-4">Training script</p>
      <CodeBlock code={snippets.script} />
      <p className="text-sm font-medium mb-2 mt-4">Recovery</p>
      <CodeBlock code={snippets.recovery} />
      <div className="mt-4">
        <Button
          variant="secondary"
          size="sm"
          onClick={() => void navigator.clipboard.writeText(snippets.script)}
        >
          Copy training script
        </Button>
      </div>
    </Card>
  );
}
