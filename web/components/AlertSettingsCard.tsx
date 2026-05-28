"use client";

import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import type { AlertSettings } from "@/lib/types";

export function AlertSettingsCard({
  alertSettings,
  onAlertChange,
  onSaveAlerts,
  savingAlerts,
}: {
  alertSettings: AlertSettings | null;
  onAlertChange: (field: keyof AlertSettings, value: string) => void;
  onSaveAlerts: () => void;
  savingAlerts: boolean;
}) {
  return (
    <Card>
      <CardTitle>Alert delivery</CardTitle>
      <CardDescription className="mt-1 space-y-2">
        <p>
          Discord or Slack webhooks work immediately. Email needs SMTP configured on the API
          host (<code className="text-xs">FAULTLINE_SMTP_HOST</code> on Render).
        </p>
        <p className="text-xs">
          Alerts fire when a run stops, fails, goes stale, or has checkpoint problems.
        </p>
      </CardDescription>
      <div className="mt-4 space-y-3">
        <label className="block text-sm">
          <span className="text-muted">Alert email</span>
          <input
            type="email"
            className="mt-1 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm"
            placeholder="you@example.com"
            value={alertSettings?.alert_email ?? ""}
            onChange={(e) => onAlertChange("alert_email", e.target.value)}
          />
        </label>
        <label className="block text-sm">
          <span className="text-muted">Discord webhook URL</span>
          <input
            type="url"
            className="mt-1 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm"
            placeholder="https://discord.com/api/webhooks/..."
            value={alertSettings?.discord_webhook_url ?? ""}
            onChange={(e) => onAlertChange("discord_webhook_url", e.target.value)}
          />
        </label>
        <label className="block text-sm">
          <span className="text-muted">Slack webhook URL</span>
          <input
            type="url"
            className="mt-1 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm"
            placeholder="https://hooks.slack.com/services/..."
            value={alertSettings?.slack_webhook_url ?? ""}
            onChange={(e) => onAlertChange("slack_webhook_url", e.target.value)}
          />
        </label>
        <button
          type="button"
          onClick={onSaveAlerts}
          disabled={savingAlerts}
          className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {savingAlerts ? "Saving…" : "Save alert settings"}
        </button>
      </div>
    </Card>
  );
}
