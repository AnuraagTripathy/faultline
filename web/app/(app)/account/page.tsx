"use client";

import { AppShell } from "@/components/AppShell";
import { StatCard } from "@/components/StatCard";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { AlertSettingsCard } from "@/components/AlertSettingsCard";
import {
  createApiKey,
  fetchAlertSettings,
  fetchApiKeys,
  fetchMe,
  updateAlertSettings,
  fetchConnectedAccounts,
  ApiError,
} from "@/lib/api";
import { formatBytes, formatTimestamp } from "@/lib/format";
import {
  ONBOARDING_API_KEY_STORAGE,
} from "@/lib/starter-script";
import type {
  AlertSettings,
  ApiKeyListItem,
  MeResponse,
  ConnectedAccount,
} from "@/lib/types";
import { Check, Copy, KeyRound, Plus, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

export default function AccountPage() {
  const [me, setMe] = useState<MeResponse | null>(null);
  const [keys, setKeys] = useState<ApiKeyListItem[]>([]);
  const [newKey, setNewKey] = useState<string | null>(null);
  const [label, setLabel] = useState("my-laptop");
  const [creating, setCreating] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [alertSettings, setAlertSettings] = useState<AlertSettings | null>(null);
  const [savingAlerts, setSavingAlerts] = useState(false);
  const [connectedAccounts, setConnectedAccounts] = useState<ConnectedAccount[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [meData, keyList, alerts] = await Promise.all([
        fetchMe(),
        fetchApiKeys(),
        fetchAlertSettings(),
      ]);
      setMe(meData);
      setKeys(keyList);
      setAlertSettings(alerts);
      try {
        setConnectedAccounts(await fetchConnectedAccounts());
      } catch {
        setConnectedAccounts([]);
      }
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load account");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function handleCreateKey() {
    const trimmed = label.trim();
    if (!trimmed) {
      setError("Enter a label for the API key");
      return;
    }
    setCreating(true);
    setError(null);
    try {
      const result = await createApiKey(trimmed);
      setNewKey(result.api_key);
      if (typeof window !== "undefined") {
        localStorage.setItem(ONBOARDING_API_KEY_STORAGE, result.api_key);
      }
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to create key");
    } finally {
      setCreating(false);
    }
  }

  async function copyNewKey() {
    if (!newKey) return;
    await navigator.clipboard.writeText(newKey);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  const u = me?.usage;

  return (
    <AppShell
      title="API Keys & Account"
      subtitle="Create keys for training scripts — shown once at creation"
      actions={
        <Button variant="secondary" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      }
    >
      {error ? <p className="text-danger text-sm mb-4">{error}</p> : null}

      <Card className="mb-6">
        <CardTitle className="flex items-center gap-2">
          <KeyRound className="h-5 w-5 text-accent" />
          Create API key
        </CardTitle>
        <CardDescription className="mt-2">
          Signed in as {me?.user.email ?? "—"}
        </CardDescription>
        <p className="text-sm text-muted mt-2">
          Create API keys for <code>faultline.start(..., api_key=...)</code> on your
          training machines. The browser dashboard uses your login session — no{" "}
          <code>FAULTLINE_API_KEY</code> env var needed for normal use.
        </p>
        <div className="mt-4 flex flex-wrap gap-2 items-end">
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-muted">Label</span>
            <input
              type="text"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="my-laptop"
              className="rounded-md border border-border bg-surface-2 px-3 py-2 text-sm min-w-[200px]"
            />
          </label>
          <Button
            type="button"
            variant="secondary"
            onClick={handleCreateKey}
            disabled={creating}
          >
            <Plus className="h-4 w-4" />
            {creating ? "Creating…" : "Create API key"}
          </Button>
        </div>
        {newKey ? (
          <div className="mt-4 rounded-lg border border-ok/40 bg-ok/10 p-4">
            <p className="text-sm text-ok font-medium mb-2">
              Copy this key now — it won&apos;t be shown again
            </p>
            <div className="flex flex-wrap items-start gap-2">
              <code className="text-xs break-all flex-1">{newKey}</code>
              <Button type="button" variant="secondary" size="sm" onClick={copyNewKey}>
                {copied ? (
                  <Check className="h-4 w-4" />
                ) : (
                  <Copy className="h-4 w-4" />
                )}
                {copied ? "Copied" : "Copy"}
              </Button>
            </div>
            <p className="text-xs text-muted mt-3">
              Next: paste this key on the{" "}
              <Link href="/quickstart" className="text-accent">
                Quickstart
              </Link>{" "}
              page to generate your training script.
            </p>
          </div>
        ) : null}
      </Card>

      <Card className="mb-6">
        <CardTitle>Connected accounts</CardTitle>
        <CardDescription className="mt-1">
          Browser sign-in providers linked to this user.
        </CardDescription>
        {connectedAccounts.length === 0 ? (
          <p className="text-sm text-muted mt-3">
            No OAuth providers linked yet. You can still use email/password login.
          </p>
        ) : (
          <ul className="mt-3 space-y-2 text-sm">
            {connectedAccounts.map((account) => (
              <li
                key={`${account.provider}-${account.provider_email ?? "none"}`}
                className="flex items-center justify-between rounded-md border border-border bg-surface-2 px-3 py-2"
              >
                <div>
                  <p className="font-medium text-foreground capitalize">{account.provider}</p>
                  <p className="text-xs text-muted">{account.provider_email ?? "No public email"}</p>
                </div>
                <span className="text-xs text-ok">Connected</span>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card className="mb-6">
        <CardTitle>Your API keys</CardTitle>
        <CardDescription className="mt-1">
          Prefixes only — full keys are never stored in the browser after creation.
        </CardDescription>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-muted border-b border-border">
                <th className="pb-2 pr-4 font-medium">Label</th>
                <th className="pb-2 pr-4 font-medium">Prefix</th>
                <th className="pb-2 pr-4 font-medium">Created</th>
                <th className="pb-2 font-medium">Last used</th>
              </tr>
            </thead>
            <tbody>
              {keys.length === 0 ? (
                <tr>
                  <td colSpan={4} className="py-4 text-muted">
                    No keys yet.
                  </td>
                </tr>
              ) : (
                keys.map((key) => (
                  <tr key={key.id} className="border-b border-border/50">
                    <td className="py-2 pr-4">{key.label}</td>
                    <td className="py-2 pr-4">
                      <code className="text-accent">{key.prefix}</code>
                    </td>
                    <td className="py-2 pr-4 text-muted">
                      {formatTimestamp(key.created_at_ms)}
                    </td>
                    <td className="py-2 text-muted">
                      {formatTimestamp(key.last_used_at_ms)}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Card>

      <AlertSettingsCard
        alertSettings={alertSettings}
        onAlertChange={(field, value) =>
          setAlertSettings((prev) =>
            prev
              ? { ...prev, [field]: value || null }
              : {
                  user_id: "",
                  alert_email: null,
                  discord_webhook_url: null,
                  slack_webhook_url: null,
                  [field]: value || null,
                }
          )
        }
        onSaveAlerts={async () => {
          if (!alertSettings) return;
          setSavingAlerts(true);
          try {
            const saved = await updateAlertSettings({
              alert_email: alertSettings.alert_email || null,
              discord_webhook_url: alertSettings.discord_webhook_url || null,
              slack_webhook_url: alertSettings.slack_webhook_url || null,
            });
            setAlertSettings(saved);
          } catch (e) {
            setError(e instanceof ApiError ? e.message : "Failed to save alerts");
          } finally {
            setSavingAlerts(false);
          }
        }}
        savingAlerts={savingAlerts}
      />

      <h2 className="text-lg font-semibold mb-4">Usage</h2>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <StatCard label="Runs created" value={u?.runs_created ?? "—"} />
        <StatCard label="Metric points" value={u?.metric_points_ingested ?? "—"} />
        <StatCard label="Events" value={u?.events_ingested ?? "—"} />
        <StatCard label="Checkpoints" value={u?.checkpoints_created ?? "—"} />
        <StatCard
          label="Checkpoint bytes"
          value={formatBytes(u?.checkpoint_bytes_uploaded)}
        />
        <StatCard
          label="Last used"
          value={formatTimestamp(u?.last_used_at_ms)}
        />
      </div>
    </AppShell>
  );
}
