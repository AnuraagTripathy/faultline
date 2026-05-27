"use client";

import { useState } from "react";

export function CodeBlock({
  code,
  className,
  onCopy,
}: {
  code: string;
  className?: string;
  onCopy?: () => void;
}) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    onCopy?.();
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className={`relative ${className ?? ""}`}>
      <pre className="overflow-x-auto rounded-md border border-border bg-surface-2 p-4 text-[13px] font-mono text-foreground leading-relaxed">
        {code}
      </pre>
      <button
        type="button"
        onClick={() => void copy()}
        className="absolute top-3 right-3 text-xs text-subtle hover:text-foreground transition"
      >
        {copied ? "Copied" : "Copy"}
      </button>
    </div>
  );
}
