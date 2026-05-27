import { MarketingLayout } from "@/components/MarketingLayout";

export default function SecurityPage() {
  return (
    <MarketingLayout title="Security">
      <p>
        Faultline separates <strong className="text-foreground">browser sessions</strong> from{" "}
        <strong className="text-foreground">training API keys</strong>. The dashboard never embeds your API key
        in client-side JavaScript for data reads — the Next.js BFF forwards your HttpOnly session as a
        short-lived JWT.
      </p>
      <ul className="list-disc pl-5 space-y-2">
        <li>Passwords hashed with bcrypt at signup</li>
        <li>API keys stored server-side; only a prefix shown in the UI</li>
        <li>JWT signed with <code className="text-accent">FAULTLINE_JWT_SECRET</code> (rotate in production)</li>
        <li>Checkpoints in object storage — not in Postgres rows</li>
        <li>CORS restricted via <code className="text-accent">FAULTLINE_CORS_ORIGINS</code></li>
      </ul>
      <p>
        Pickle checkpoints can execute arbitrary code on load — only restore checkpoints you created.
        See <code className="text-accent">SECURITY.md</code> in the repo for reporting vulnerabilities.
      </p>
    </MarketingLayout>
  );
}
