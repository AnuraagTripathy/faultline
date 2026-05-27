import { MarketingLayout } from "@/components/MarketingLayout";

export default function ReliabilityPage() {
  return (
    <MarketingLayout title="Reliability">
      <p>
        <strong className="text-foreground">Built for long-running jobs</strong> on HPC + cloud GPUs where
        failures are expected and recoverability matters more than perfect uptime.
      </p>
      <h2 className="text-xl font-semibold text-foreground">What we provide</h2>
      <ul className="list-disc pl-5 space-y-2">
        <li>Durable checkpoint storage (S3-compatible / MinIO)</li>
        <li>Checkpoint verification and health badges before resume</li>
        <li>Background worker for alert evaluation and resume tasks</li>
        <li>Retries on storage operations in the SDK and API paths</li>
        <li>Recovery summaries with estimated lost steps and resume snippets</li>
      </ul>
      <h2 className="text-xl font-semibold text-foreground">What we do not guarantee</h2>
      <ul className="list-disc pl-5 space-y-2">
        <li>Zero data loss on catastrophic storage failure (use bucket replication)</li>
        <li>Automatic distributed training coordination across nodes</li>
        <li>Exact step-level reproducibility after hardware changes</li>
        <li>99.99% SLA on the open-source Docker stack (bring your own HA)</li>
      </ul>
    </MarketingLayout>
  );
}
