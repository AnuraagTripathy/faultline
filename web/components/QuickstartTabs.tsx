"use client";

import { CodeBlock } from "@/components/CodeBlock";
import { cn } from "@/lib/cn";
import { useState } from "react";

const TABS = [
  { id: "laptop", label: "Laptop" },
  { id: "hpc", label: "HPC / Slurm" },
  { id: "cloud", label: "Cloud GPU" },
] as const;

const CONTENT: Record<(typeof TABS)[number]["id"], { title: string; code: string }> = {
  laptop: {
    title: "Train on your laptop",
    code: `# Terminal 1 — API
uvicorn cloud.api.app:app --reload --port 8080

# Terminal 2 — training (runs locally, streams to cloud)
set PYTHONPATH=sdk
python sdk/examples/cloud_pytorch_easy.py

# Browser — Next.js UI
cd web && npm run dev
# http://localhost:3000`,
  },
  hpc: {
    title: "HPC / Slurm cluster",
    code: `import faultline
import os

run = faultline.start(
    "cluster-run",
    project="physics",
    api_key=os.environ["FAULTLINE_API_KEY"],
    base_url=os.environ.get("FAULTLINE_API_URL", "http://127.0.0.1:8080"),
)
run.register_slurm_script("train.slurm")

for step in range(start_step, max_steps):
    run.log(loss=loss, step=step)
    if step % 500 == 0:
        run.save(model=model, optimizer=optimizer, step=step)

# After node failure: dashboard → Resume Run
# Or: run.resume()  # runs sbatch train.slurm`,
  },
  cloud: {
    title: "Cloud GPU VM",
    code: `# On the GPU instance
export FAULTLINE_API_KEY=your-api-key-from-account-page
export FAULTLINE_API_URL=https://your-faultline-api.example.com

pip install -e sdk
python train.py  # uses faultline.start(..., base_url=..., api_key=...)

# Point web UI BFF at your API (server .env.local):
# FAULTLINE_API_URL=https://your-faultline-api.example.com
# FAULTLINE_API_KEY=your-server-bff-key`,
  },
};

export function QuickstartTabs() {
  const [tab, setTab] = useState<(typeof TABS)[number]["id"]>("laptop");
  const active = CONTENT[tab];

  return (
    <div>
      <div className="flex flex-wrap gap-2 border-b border-border mb-4">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={cn(
              "px-4 py-2 text-sm font-medium border-b-2 -mb-px transition",
              tab === t.id
                ? "border-accent text-accent"
                : "border-transparent text-muted hover:text-foreground"
            )}
          >
            {t.label}
          </button>
        ))}
      </div>
      <h3 className="text-lg font-semibold mb-3">{active.title}</h3>
      <CodeBlock code={active.code} />
    </div>
  );
}
