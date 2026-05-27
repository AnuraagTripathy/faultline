import { MarketingLayout } from "@/components/MarketingLayout";

export default function ArchitecturePage() {
  return (
    <MarketingLayout title="Architecture">
      <p>
        Faultline is an <strong className="text-foreground">ML training continuity and recovery platform</strong>.
        Training scripts send metrics and checkpoints to a Cloud API; Postgres stores metadata; object
        storage holds checkpoint blobs; the Next.js dashboard proxies through your login session.
      </p>
      <pre className="rounded-lg border border-border bg-surface-2 p-4 text-xs text-foreground overflow-x-auto font-mono">
{`[Trainer / HF / Lightning / SDK]
        |  HTTPS + API key
   Cloud API (FastAPI)
        |
   PostgreSQL + MinIO/S3
        |
   Dashboard (Next.js BFF + JWT)`}
      </pre>
      <p>
        <strong className="text-foreground">Built for long-running ML jobs</strong> on laptops, HPC clusters,
        and cloud GPUs. The local Rust runtime remains available for offline checkpoint experiments.
      </p>
      <p>Full details in the repository: <code className="text-accent">docs/ARCHITECTURE.md</code></p>
    </MarketingLayout>
  );
}
