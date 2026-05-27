import { AppShell } from "@/components/AppShell";
import { QuickstartSnippet } from "@/components/QuickstartSnippet";
import { QuickstartWizard } from "@/components/QuickstartWizard";
import { QuickstartTabs } from "@/components/QuickstartTabs";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import Link from "next/link";

export default function QuickstartPage() {
  return (
    <AppShell
      title="Quickstart"
      subtitle="Create an API key, copy a snippet, and run your first training job"
    >
      <div className="max-w-3xl space-y-8">
        <QuickstartSnippet />

        <QuickstartWizard />

        <Card>
          <CardTitle>Where are you training?</CardTitle>
          <CardDescription className="mb-4">
            Same SDK everywhere — metrics and checkpoints stream to Faultline Cloud.
          </CardDescription>
          <QuickstartTabs />
        </Card>

        <Card>
          <CardTitle>Web dashboard</CardTitle>
          <CardDescription>
            The Next.js app uses a server-side proxy for dashboard reads. Training
            scripts use the API key you create on{" "}
            <Link href="/account" className="text-accent">
              Account
            </Link>
            . Open <Link href="/dashboard">Dashboard</Link> after your first run.
          </CardDescription>
        </Card>
      </div>
    </AppShell>
  );
}
