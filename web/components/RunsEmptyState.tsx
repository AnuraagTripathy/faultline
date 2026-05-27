import { CodeBlock } from "@/components/CodeBlock";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { STARTER_SCRIPT } from "@/lib/starter-script";
import Link from "next/link";
import { Rocket } from "lucide-react";

export function RunsEmptyState() {
  return (
    <Card className="text-center py-10 px-6">
      <Rocket className="h-10 w-10 text-accent mx-auto mb-4" />
      <CardTitle>No training runs yet</CardTitle>
      <CardDescription className="max-w-md mx-auto mt-2 mb-6">
        Start the Faultline Cloud API, then run a script with{" "}
        <code className="text-accent">faultline.start()</code>. Your runs will
        appear here with live metrics and recovery tools.
      </CardDescription>
      <div className="flex flex-wrap justify-center gap-3 mb-6">
        <Link href="/quickstart">
          <Button>Open Quickstart</Button>
        </Link>
        <Link href="/demo">
          <Button variant="secondary">View live demo</Button>
        </Link>
        <p className="w-full text-xs text-muted mt-2">
          Docker users: log in as <code className="text-accent">demo@faultline.local</code> /{" "}
          <code className="text-accent">faultlinedemo</code> to see pre-seeded runs.
        </p>
      </div>
      <div className="text-left max-w-lg mx-auto">
        <p className="text-sm text-muted mb-2">Starter script</p>
        <CodeBlock code={STARTER_SCRIPT} />
      </div>
    </Card>
  );
}
