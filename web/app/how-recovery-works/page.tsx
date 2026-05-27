import { MarketingLayout } from "@/components/MarketingLayout";

export default function HowRecoveryWorksPage() {
  return (
    <MarketingLayout title="How Recovery Works">
      <p>
        Faultline is built for long-running jobs where failures are normal. We persist checkpoint
        blobs in object storage, store run metadata in Postgres, and compute recovery guidance from
        both signals.
      </p>
      <h2 className="text-xl font-semibold text-foreground">Recovery semantics</h2>
      <ul className="list-disc pl-5 space-y-2">
        <li>Recovery can resume from the latest committed checkpoint only.</li>
        <li>Estimated lost steps = latest metric step minus latest checkpoint step.</li>
        <li>Stale-run detection marks jobs with no metrics for an extended period.</li>
        <li>Resume commands are generated from launch config + checkpoint state.</li>
      </ul>
      <h2 className="text-xl font-semibold text-foreground">Durability model</h2>
      <ul className="list-disc pl-5 space-y-2">
        <li>Checkpoint bytes are written to S3-compatible storage before commit status is shown.</li>
        <li>Checksums are stored and can be validated by background verification tasks.</li>
        <li>Dashboard badges expose checkpoint health and restore readiness.</li>
      </ul>
      <p>
        Faultline does not guarantee zero loss under catastrophic storage failures. Use bucket
        versioning/replication for production-grade durability.
      </p>
    </MarketingLayout>
  );
}
