"use client";

import { CodeBlock } from "@/components/CodeBlock";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { fetchApiKeys } from "@/lib/api";
import {
  buildStarterScript,
  DEFAULT_API_BASE_URL,
  ONBOARDING_API_KEY_STORAGE,
  ONBOARDING_SNIPPET_COPIED_STORAGE,
} from "@/lib/starter-script";
import type { ApiKeyListItem } from "@/lib/types";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

export function QuickstartSnippet() {
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState(DEFAULT_API_BASE_URL);
  const [keys, setKeys] = useState<ApiKeyListItem[]>([]);

  useEffect(() => {
    const stored = localStorage.getItem(ONBOARDING_API_KEY_STORAGE);
    if (stored) setApiKey(stored);
    fetchApiKeys()
      .then(setKeys)
      .catch(() => setKeys([]));
  }, []);

  const snippet = useMemo(
    () => buildStarterScript(apiKey || "YOUR_API_KEY", baseUrl),
    [apiKey, baseUrl]
  );

  function handleSnippetCopy() {
    localStorage.setItem(ONBOARDING_SNIPPET_COPIED_STORAGE, "1");
  }

  return (
    <Card>
      <CardTitle>Connect your training script</CardTitle>
      <CardDescription className="mt-1 mb-4">
        Create a key on{" "}
        <Link href="/account" className="text-accent">
          Account
        </Link>
        , paste it below, and copy the generated snippet into your trainer.
      </CardDescription>

      <div className="grid gap-4 sm:grid-cols-2 mb-4">
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-muted">API key</span>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => {
              setApiKey(e.target.value);
              localStorage.setItem(ONBOARDING_API_KEY_STORAGE, e.target.value);
            }}
            placeholder="fl_… (paste after creating on Account)"
            className="rounded-md border border-border bg-surface-2 px-3 py-2 text-sm font-mono"
            autoComplete="off"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-muted">API base URL</span>
          <input
            type="text"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder={DEFAULT_API_BASE_URL}
            className="rounded-md border border-border bg-surface-2 px-3 py-2 text-sm font-mono"
          />
        </label>
      </div>

      {keys.length > 0 ? (
        <div className="mb-4">
          <p className="text-xs text-muted mb-2">Your keys (prefix only):</p>
          <div className="flex flex-wrap gap-2">
            {keys.map((key) => (
              <span
                key={key.id}
                className="rounded-md border border-border bg-surface-2 px-2 py-1 text-xs"
                title="Full key is only shown once at creation — paste it above"
              >
                {key.label}: <code>{key.prefix}</code>
              </span>
            ))}
          </div>
        </div>
      ) : null}

      {!apiKey ? (
        <p className="text-sm text-muted mb-3">
          No key pasted yet.{" "}
          <Link href="/account" className="text-accent">
            Create one on Account
          </Link>
          .
        </p>
      ) : null}

      <CodeBlock code={snippet} onCopy={handleSnippetCopy} />

      <div className="mt-4 flex flex-wrap gap-2">
        <Link href="/account" className="no-underline hover:no-underline">
          <Button variant="secondary" size="sm">Create API key</Button>
        </Link>
        <Link href="/dashboard" className="no-underline hover:no-underline">
          <Button variant="secondary" size="sm">Open dashboard</Button>
        </Link>
      </div>
    </Card>
  );
}
